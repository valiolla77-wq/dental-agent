import json
import os
import unittest
from datetime import datetime, time

os.environ.setdefault(
    "CONFIRMATION_HMAC_SECRET",
    "test-confirmation-hmac-secret-32-chars-long",
)

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import TOOL_REGISTRY, agent_graph, create_initial_state
from app.errors import AppError
from app.models.agent_confirmation import AgentConfirmation
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.user import User


class FakeChatModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.received = []
        self.tool_schemas = []

    def bind_tools(self, tool_schemas):
        self.tool_schemas = list(tool_schemas)
        return self

    async def ainvoke(self, messages):
        self.received.append(list(messages))
        return self.responses.pop(0)


def _call(name, arguments, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": arguments, "id": call_id, "type": "tool_call"}],
    )


class AgentGraphTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        async with self.session_factory() as db:
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار نمونه گراف",
                phone="09000000000",
            )
            self.doctor = Doctor(
                full_name="پزشک نمونه گراف",
                specialty="تخصص نمونه",
                phone="09000000001",
            )
            self.service = DentalService(name="خدمت نمونه گراف", is_active=True)
            self.doctor.dental_services = [self.service]
            db.add_all([self.patient, self.doctor, self.service])
            await db.commit()
            await db.refresh(self.patient)
            await db.refresh(self.doctor)
            await db.refresh(self.service)
            db.add(
                DoctorSchedule(
                    doctor_id=self.doctor.id,
                    day_of_week=0,
                    start_time=time(9),
                    end_time=time(13),
                    slot_duration_minutes=30,
                    is_active=True,
                )
            )
            self.appointment = Appointment(
                patient_id=self.patient.id,
                doctor_id=self.doctor.id,
                service_id=self.service.id,
                appointment_time=datetime(2026, 10, 10, 10),
                status="scheduled",
            )
            db.add(self.appointment)
            await db.commit()
            await db.refresh(self.appointment)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _add_same_slot_second_appointment(self):
        """Create a second scheduled appointment for the same patient/time."""
        async with self.session_factory() as db:
            doctor = Doctor(
                full_name="دکتر مینا رضایی",
                specialty="تخصص دوم",
                phone="09000000002",
                is_active=True,
            )
            service = DentalService(
                name="خدمت ویژه دوم",
                is_active=True,
            )
            doctor.dental_services = [service]
            db.add_all([doctor, service])
            await db.commit()
            await db.refresh(doctor)
            await db.refresh(service)
            appointment = Appointment(
                patient_id=self.patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=self.appointment.appointment_time,
                status="scheduled",
            )
            db.add(appointment)
            await db.commit()
            await db.refresh(appointment)
            return appointment, doctor, service

    async def _confirmation_rows(self, session_id):
        async with self.session_factory() as db:
            result = await db.execute(
                select(AgentConfirmation).where(
                    AgentConfirmation.session_id == session_id
                )
            )
            return list(result.scalars().all())

    async def _invoke(self, state, model=None, *, session_id=None, confirmation=None):
        async with self.session_factory() as db:
            context = {
                "db": db,
                "llm": model or FakeChatModel(AIMessage(content="پاسخ آزمایشی")),
                # Fixed clock keeps past/future assertions reproducible.
                "now": datetime(2026, 10, 10, 8, 0),
                # Trusted server-side actor for tool authorization checks.
                "actor": User(
                    id=1,
                    full_name="Graph Probe",
                    phone="09900000111",
                    password_hash="unused-hash",
                    role="receptionist",
                    is_active=True,
                ),
            }
            if session_id is not None:
                context["session_id"] = session_id
            if confirmation is not None:
                context["confirmation"] = confirmation
            return await agent_graph.ainvoke(state, context=context)

    def test_initial_state_has_minimal_agent_fields(self):
        state = create_initial_state(
            messages=[{"role": "user", "content": "خدمت‌ها را نشان بده"}],
            intent="search_services",
            service_id=4,
        )
        self.assertEqual(state["messages"][0]["role"], "user")
        self.assertEqual(state["intent"], "search_services")
        self.assertEqual(state["service_id"], 4)
        self.assertIsNone(state["pending_action"])
        self.assertFalse(state["confirmation_required"])
        self.assertIsNone(state["last_tool_result"])

    async def test_simple_message_gets_direct_response_without_a_real_llm(self):
        model = FakeChatModel(AIMessage(content="سلام، چطور کمک کنم؟"))
        result = await self._invoke(
            create_initial_state(messages=[{"role": "user", "content": "سلام"}]),
            model,
        )
        self.assertEqual(result["final_response"], "سلام، چطور کمک کنم؟")
        self.assertEqual(len(model.received), 1)
        # No database/session internals may leak into the model messages. The
        # check is specific because the word "db" legitimately occurs inside
        # the tool name ``submit_feedback``.
        representation = repr(model.received[0])
        for marker in ("AsyncSession", "sqlalchemy", "object at 0x"):
            self.assertNotIn(marker, representation)

    async def test_read_tool_is_selected_and_tool_result_returns_to_llm(self):
        model = FakeChatModel(
            _call("search_dental_services", {"query": "نمونه"}),
            AIMessage(content="یک خدمت فعال پیدا شد."),
        )
        result = await self._invoke(
            create_initial_state(messages=[{"role": "user", "content": "خدمت نمونه"}]),
            model,
        )
        self.assertTrue(result["last_tool_result"]["ok"])
        self.assertEqual(result["last_tool_result"]["data"][0]["id"], self.service.id)
        self.assertEqual(result["final_response"], "یک خدمت فعال پیدا شد.")
        self.assertIsInstance(model.received[1][-1], ToolMessage)
        tool_payload = json.loads(model.received[1][-1].content)
        self.assertTrue(tool_payload["ok"])
        self.assertEqual(model.tool_schemas[0]["function"]["name"], "search_dental_services")

    async def test_error_from_tool_is_returned_to_llm_with_catalog_code(self):
        model = FakeChatModel(
            _call("find_doctors_for_service", {"service_id": 999}),
            AIMessage(content="خدمت موردنظر در سامانه پیدا نشد."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertFalse(result["last_tool_result"]["ok"])
        self.assertEqual(result["last_tool_error"].code, "DENTAL_SERVICE_NOT_FOUND")
        llm_tool_output = json.loads(model.received[1][-1].content)
        self.assertEqual(llm_tool_output["error"]["code"], "DENTAL_SERVICE_NOT_FOUND")
        self.assertIn("خدمت", llm_tool_output["error"]["message"])
        self.assertEqual(result["final_response"], "خدمت موردنظر در سامانه پیدا نشد.")

    async def test_llm_exception_details_are_not_logged_or_returned(self):
        secret_marker = "private-provider-error-detail"

        class FailingChatModel:
            def bind_tools(self, _tool_schemas):
                return self

            async def ainvoke(self, _messages):
                raise RuntimeError(secret_marker)

        with self.assertLogs("dental_agent.agent", level="ERROR") as captured:
            result = await self._invoke(create_initial_state(), FailingChatModel())

        self.assertEqual(result["last_tool_error"].code, "INTERNAL_ERROR")
        self.assertNotIn(secret_marker, result["final_response"])
        self.assertNotIn(secret_marker, "\n".join(captured.output))

    async def test_provider_rate_limit_surfaces_retryable_app_error(self):
        class RateLimitError(Exception):
            status_code = 429

        class ThrottledChatModel:
            def bind_tools(self, _tool_schemas):
                return self

            async def ainvoke(self, _messages):
                raise RateLimitError("provider says slow down")

        with self.assertRaises(AppError) as raised:
            await self._invoke(create_initial_state(), ThrottledChatModel())

        self.assertEqual(raised.exception.code, "AGENT_PROVIDER_RATE_LIMITED")
        self.assertEqual(raised.exception.status_code, 503)

    async def test_llm_can_call_multiple_tools_in_sequence(self):
        model = FakeChatModel(
            _call("search_dental_services", {"query": "نمونه"}, "call-search"),
            _call(
                "find_doctors_for_service",
                {"service_id": self.service.id},
                "call-doctors",
            ),
            AIMessage(content="پزشک ارائه‌دهنده پیدا شد."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertEqual(result["final_response"], "پزشک ارائه‌دهنده پیدا شد.")
        self.assertEqual(len(model.received), 3)
        self.assertEqual(
            [m.name for m in model.received[2] if isinstance(m, ToolMessage)],
            ["search_dental_services", "find_doctors_for_service"],
        )

    async def test_multiple_calls_in_one_llm_response_are_dispatched_generically(self):
        model = FakeChatModel(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_dental_services", "args": {"query": "نمونه"}, "id": "a", "type": "tool_call"},
                    {"name": "find_doctors_for_service", "args": {"service_id": self.service.id}, "id": "b", "type": "tool_call"},
                ],
            ),
            AIMessage(content="نتیجه دریافت شد."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertEqual(result["final_response"], "نتیجه دریافت شد.")
        self.assertEqual(len(model.received), 2)
        self.assertEqual(
            [m.name for m in model.received[1] if isinstance(m, ToolMessage)],
            ["search_dental_services", "find_doctors_for_service"],
        )

    async def test_read_and_write_tools_are_classified_in_registry(self):
        reads = {
            "search_dental_services", "find_doctors_for_service",
            "find_available_slots", "find_nearest_appointments",
            "get_patient_appointments",
        }
        writes = {"book_appointment", "cancel_appointment", "reschedule_appointment"}
        self.assertTrue(all(TOOL_REGISTRY[name].operation == "read" for name in reads))
        self.assertTrue(all(TOOL_REGISTRY[name].operation == "write" for name in writes))

    async def test_write_waits_for_confirmation_and_persists_pending_action(self):
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id})
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["confirmation_status"], "pending")
        self.assertEqual(result["pending_action"]["tool_name"], "cancel_appointment")
        prompt = result["confirmation_prompt"]
        self.assertNotIn("شماره", prompt)
        self.assertNotRegex(prompt, r"نوبت\s+\d")
        self.assertIn("لغو نوبت", prompt)
        self.assertIn(self.doctor.full_name, prompt)
        self.assertIn(self.service.name, prompt)
        self.assertIn("ساعت ۱۰:۰۰", prompt)
        self.assertIsNone(result["last_tool_result"])
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_write_executes_only_after_confirmation(self):
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
            AIMessage(content="نوبت لغو شد."),
        )
        pending = await self._invoke(create_initial_state(), model)
        self.assertTrue(pending["confirmation_token"])
        result = await self._invoke(
            pending,
            model,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertTrue(result["last_tool_result"]["ok"])
        self.assertEqual(result["last_tool_result"]["data"]["status"], "cancelled")
        self.assertIsNone(result["pending_action"])
        self.assertFalse(result["confirmation_required"])

    async def test_rejected_confirmation_never_calls_write_tool(self):
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id})
        )
        pending = await self._invoke(create_initial_state(), model)
        pending["confirmation_status"] = "rejected"
        result = await self._invoke(pending, model)
        self.assertEqual(result["final_response"], "درخواست انجام نشد.")
        self.assertIsNone(result["last_tool_result"])
        self.assertEqual(len(model.received), 1)
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_forged_confirmation_status_in_state_cannot_execute_write(self):
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
        )
        pending = await self._invoke(create_initial_state(), model)
        forged = {**pending, "confirmation_status": "approved"}
        result = await self._invoke(forged, model)
        self.assertIsNone(result["last_tool_result"])
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(result["confirmation_status"], "pending")
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_tampered_arguments_after_display_reject_execution(self):
        session = "sess-tamper-guard"
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
        )
        pending = await self._invoke(create_initial_state(), model, session_id=session)
        token = pending["confirmation_token"]
        tampered = {
            **pending,
            "pending_action": {
                **pending["pending_action"],
                "arguments": {"appointment_id": self.appointment.id + 999},
            },
        }
        result = await self._invoke(
            tampered,
            model,
            session_id=session,
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(result["final_response"], "درخواست انجام نشد.")
        self.assertIsNone(result["pending_action"])
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_confirmation_for_previous_operation_cannot_approve_new_operation(self):
        session = "sess-reuse-guard"
        model1 = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
            AIMessage(content="نوبت لغو شد."),
        )
        pending1 = await self._invoke(create_initial_state(), model1, session_id=session)
        old_token = pending1["confirmation_token"]
        result1 = await self._invoke(
            pending1,
            model1,
            session_id=session,
            confirmation={"token": old_token, "decision": "approved"},
        )
        self.assertTrue(result1["last_tool_result"]["ok"])

        # A new write proposal opens a fresh confirmation for the same session.
        async with self.session_factory() as db:
            second_appointment = Appointment(
                patient_id=self.patient.id,
                doctor_id=self.doctor.id,
                service_id=self.service.id,
                appointment_time=datetime(2026, 10, 10, 11),
                status="scheduled",
            )
            db.add(second_appointment)
            await db.commit()
            await db.refresh(second_appointment)
            second_appointment_id = second_appointment.id
        model2 = FakeChatModel(
            _call(
                "cancel_appointment",
                {"appointment_id": second_appointment_id},
            ),
        )
        pending2 = await self._invoke(
            create_initial_state(messages=result1["messages"]),
            model2,
            session_id=session,
        )
        self.assertTrue(pending2["confirmation_token"])
        self.assertNotEqual(old_token, pending2["confirmation_token"])

        # The previous operation's confirmation must not approve the new one.
        forged = {**pending2, "confirmation_status": "approved"}
        result2 = await self._invoke(
            forged,
            model2,
            session_id=session,
            confirmation={"token": old_token, "decision": "approved"},
        )
        self.assertEqual(result2["final_response"], "درخواست انجام نشد.")
        self.assertIsNone(result2["pending_action"])
        self.assertEqual(len(model2.received), 1)

    async def test_consumed_confirmation_cannot_reexecute_same_operation(self):
        session = "sess-replay-guard"
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
            AIMessage(content="نوبت لغو شد."),
        )
        pending = await self._invoke(create_initial_state(), model, session_id=session)
        token = pending["confirmation_token"]
        result = await self._invoke(
            pending,
            model,
            session_id=session,
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertTrue(result["last_tool_result"]["ok"])

        # Replay: restore the consumed pending action and reuse the same token.
        replay_state = {
            **result,
            "pending_action": pending["pending_action"],
            "confirmation_status": "approved",
        }
        replay = await self._invoke(
            replay_state,
            model,
            session_id=session,
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(replay["final_response"], "درخواست انجام نشد.")
        self.assertIsNone(replay["pending_action"])
        self.assertEqual(len(model.received), 2)

    async def test_context_rejection_never_calls_write_tool(self):
        session = "sess-context-reject"
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
        )
        pending = await self._invoke(create_initial_state(), model, session_id=session)
        result = await self._invoke(
            pending,
            model,
            session_id=session,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "rejected",
            },
        )
        self.assertEqual(result["final_response"], "درخواست انجام نشد.")
        self.assertIsNone(result["last_tool_result"])
        self.assertEqual(len(model.received), 1)
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_approval_from_another_session_is_rejected(self):
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
        )
        pending = await self._invoke(
            create_initial_state(), model, session_id="sess-owner"
        )
        token = pending["confirmation_token"]
        result = await self._invoke(
            pending,
            model,
            session_id="sess-attacker",
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(result["final_response"], "درخواست انجام نشد.")
        self.assertIsNone(result["pending_action"])
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_route_injection_cannot_bypass_confirmation(self):
        model = FakeChatModel(AIMessage(content="متوجه نشدم."))
        injected = create_initial_state()
        injected["route"] = "execute_tool"
        injected["selected_tool"] = "cancel_appointment"
        injected["selected_tool_arguments"] = {"appointment_id": self.appointment.id}
        injected["pending_tool_calls"] = [
            {"tool_name": "__unknown_tool__", "arguments": {}, "tool_call_id": "bad-1"}
        ]
        result = await self._invoke(injected, model)
        self.assertEqual(
            result["last_tool_result"]["error"]["code"], "COMMON_VALIDATION_ERROR"
        )
        self.assertEqual(result["final_response"], "متوجه نشدم.")
        self.assertEqual(len(model.received), 1)
        async with self.session_factory() as db:
            stored = await db.get(Appointment, self.appointment.id)
        self.assertEqual(stored.status, "scheduled")

    async def test_sensitive_tool_fields_are_not_sent_back_in_later_llm_turn(self):
        model = FakeChatModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": self.doctor.id,
                    "service_id": self.service.id,
                    "appointment_date": "1405/07/18",
                    "appointment_time": "11:00",
                    "national_id": "0000000000",
                    "full_name": "بیمار محرمانه",
                    "phone": "09000000000",
                    "reason": "اطلاعات خصوصی",
                },
            )
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertTrue(result["confirmation_required"])
        self.assertIn("0000000000", repr(result["pending_action"]))
        # Confirmation summary and recorded assistant tool-call history omit PII.
        self.assertNotIn("0000000000", result["confirmation_prompt"])
        self.assertNotIn("0000000000", repr(result["messages"][-1]))

    async def test_llm_does_not_receive_database_session(self):
        model = FakeChatModel(AIMessage(content="پاسخ"))
        await self._invoke(create_initial_state(), model)
        self.assertTrue(all(isinstance(message, object) for message in model.received[0]))
        self.assertFalse(any(hasattr(message, "execute") for message in model.received[0]))

    async def test_unknown_tool_call_returns_catalog_validation_error(self):
        model = FakeChatModel(
            _call("execute_sql", {"query": "select 1"}),
            AIMessage(content="این عملیات قابل انجام نیست."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertEqual(result["last_tool_error"].code, "COMMON_VALIDATION_ERROR")
        self.assertEqual(len(model.received), 2)
        payload = json.loads(model.received[1][-1].content)
        self.assertEqual(payload["error"]["code"], "COMMON_VALIDATION_ERROR")

    async def _statuses(self):
        async with self.session_factory() as db:
            first = await db.get(Appointment, self.appointment.id)
            second = await db.get(Appointment, self.second_appointment.id)
            return first.status, second.status

    async def test_ambiguous_cancel_requires_clarification_and_no_write(self):
        (
            self.second_appointment,
            _,
            _,
        ) = await self._add_same_slot_second_appointment()
        session = "sess-ambiguous-cancel"
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id})
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت 1405/07/18 ساعت 10:00 را لغو کن",
                    }
                ]
            ),
            model,
            session_id=session,
        )

        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertIn("چند نوبت", result["final_response"])
        self.assertEqual(
            await self._statuses(), ("scheduled", "scheduled")
        )
        self.assertEqual(await self._confirmation_rows(session), [])

    async def test_ambiguous_reschedule_requires_clarification_and_no_write(self):
        (
            self.second_appointment,
            _,
            _,
        ) = await self._add_same_slot_second_appointment()
        session = "sess-ambiguous-reschedule"
        model = FakeChatModel(
            _call(
                "reschedule_appointment",
                {
                    "appointment_id": self.appointment.id,
                    "appointment_date": "1405/07/18",
                    "appointment_time": "11:00",
                },
            )
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت 1405/07/18 ساعت 10:00 را جابه‌جا کن",
                    }
                ]
            ),
            model,
            session_id=session,
        )

        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertIn("چند نوبت", result["final_response"])
        self.assertEqual(
            await self._statuses(), ("scheduled", "scheduled")
        )
        self.assertEqual(await self._confirmation_rows(session), [])

    async def test_exact_cancel_targets_only_the_named_appointment(self):
        (
            self.second_appointment,
            _,
            _,
        ) = await self._add_same_slot_second_appointment()
        session = "sess-exact-cancel"
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
            AIMessage(content="نوبت لغو شد."),
        )
        request = (
            f"نوبت خدمت {self.service.name} با {self.doctor.full_name} "
            "در تاریخ 1405/07/18 ساعت 10:00 را لغو کن"
        )
        pending = await self._invoke(
            create_initial_state(messages=[{"role": "user", "content": request}]),
            model,
            session_id=session,
        )

        self.assertTrue(pending["confirmation_required"])
        self.assertIsNotNone(pending["confirmation_token"])
        prompt = pending["confirmation_prompt"]
        self.assertIn(self.service.name, prompt)
        self.assertIn(self.doctor.full_name, prompt)
        self.assertNotIn("شماره", prompt)
        self.assertNotRegex(prompt, r"نوبت\s+\d")
        self.assertEqual(
            await self._statuses(), ("scheduled", "scheduled")
        )

        approved = await self._invoke(
            pending,
            model,
            session_id=session,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertTrue(approved["last_tool_result"]["ok"])
        self.assertEqual(
            approved["last_tool_result"]["data"]["status"], "cancelled"
        )
        self.assertEqual(
            await self._statuses(), ("cancelled", "scheduled")
        )

    async def test_successful_cancel_final_response_redacts_appointment_id(self):
        model = FakeChatModel(
            _call("cancel_appointment", {"appointment_id": self.appointment.id}),
            AIMessage(
                content=f"نوبت شماره {self.appointment.id} لغو شد."
            ),
        )
        session = "sess-cancel-id-redaction"
        pending = await self._invoke(
            create_initial_state(),
            model,
            session_id=session,
        )
        approved = await self._invoke(
            pending,
            model,
            session_id=session,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "approved",
            },
        )

        reply = approved["final_response"]
        self.assertEqual(
            approved["last_tool_result"]["data"]["status"], "cancelled"
        )
        self.assertNotIn(f"نوبت {self.appointment.id}", reply)
        self.assertNotIn(f"شماره {self.appointment.id}", reply)
        self.assertIn("لغو شد", reply)
        self.assertIn(self.service.name, reply)
        self.assertIn(self.doctor.full_name, reply)


if __name__ == "__main__":
    unittest.main()
