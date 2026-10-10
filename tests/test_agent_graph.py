import json
import unittest
from datetime import datetime

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import TOOL_REGISTRY, agent_graph, create_initial_state
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient


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
            db.add_all([self.patient, self.doctor, self.service])
            await db.commit()
            await db.refresh(self.patient)
            await db.refresh(self.doctor)
            await db.refresh(self.service)
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

    async def _invoke(self, state, model=None):
        async with self.session_factory() as db:
            return await agent_graph.ainvoke(
                state,
                context={"db": db, "llm": model or FakeChatModel(AIMessage(content="پاسخ آزمایشی"))},
            )

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
        self.assertNotIn("db", repr(model.received[0]))

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
            "find_available_slots", "get_patient_appointments",
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
        self.assertIn(str(self.appointment.id), result["confirmation_prompt"])
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
        pending["confirmation_status"] = "approved"
        result = await self._invoke(pending, model)
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

    async def test_sensitive_tool_fields_are_not_sent_back_in_later_llm_turn(self):
        model = FakeChatModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": 1,
                    "service_id": 2,
                    "appointment_date": "1405/07/18",
                    "appointment_time": "10:00",
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


if __name__ == "__main__":
    unittest.main()
