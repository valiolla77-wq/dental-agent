"""Regression tests for server-bound identity, safe graph limits, and prompts."""

import os
import unittest
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import jdatetime
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

os.environ.setdefault(
    "CONFIRMATION_HMAC_SECRET",
    "test-confirmation-hmac-secret-32-chars-long",
)

from app.agent import agent_graph, create_initial_state
from app.agent.graph import AGENT_RECURSION_LIMIT, MAX_AGENT_STEPS
from app.agent.prompts import build_system_prompt
from app.agent.registry import get_llm_tool_schemas
from app.auth.permissions import authorize_tool_call
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.user import User
from app.utils.date_utils import gregorian_to_jalali
from app.utils.persian import to_persian_digits


def _call(name, arguments, call_id="call-1"):
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}
        ],
    )


class ScriptedModel:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.received = []
        self.schemas = []

    def bind_tools(self, schemas):
        self.schemas = list(schemas)
        return self

    async def ainvoke(self, messages):
        self.received.append(list(messages))
        return self.responses.pop(0)


class LoopingReadModel:
    """Always asks for one more read; the graph must stop predictably."""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, schemas):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return _call(
            "search_dental_services",
            {"query": "دندان"},
            call_id=f"loop-{self.calls}",
        )


class PromptAndSchemaTests(unittest.TestCase):
    def test_prompt_contains_server_owned_tehran_date_and_safety_rules(self):
        now = datetime(2026, 10, 21, 8, 30)
        prompt = build_system_prompt(now)
        jalali = jdatetime.datetime.fromgregorian(datetime=now)
        self.assertIn("چهارشنبه", prompt)
        self.assertIn(jalali.strftime("%Y/%m/%d"), prompt)
        self.assertIn("08:30", prompt)
        self.assertIn("2026-10-21", prompt)
        self.assertIn("YYYY/MM/DD", prompt)
        self.assertIn("اورژانس", prompt)
        self.assertIn("تشخیص قطعی", prompt)
        self.assertIn("داده", prompt)
        self.assertIn("دستور", prompt)

    def test_patient_bound_prompt_hides_identity_instructions(self):
        patient_prompt = build_system_prompt(
            datetime(2026, 10, 21, 8, 30), patient_bound=True
        )
        staff_prompt = build_system_prompt(
            datetime(2026, 10, 21, 8, 30), patient_bound=False
        )
        self.assertIn("خودکار", patient_prompt)
        self.assertNotIn("`national_id`", patient_prompt)
        self.assertIn("`national_id`", staff_prompt)

    def test_patient_bound_schemas_hide_identity_fields(self):
        patient_schemas = {
            item["function"]["name"]: item["function"]["parameters"]
            for item in get_llm_tool_schemas(patient_bound=True)
        }
        staff_schemas = {
            item["function"]["name"]: item["function"]["parameters"]
            for item in get_llm_tool_schemas(patient_bound=False)
        }
        for hidden in ("patient_id", "national_id", "full_name", "phone"):
            self.assertNotIn(
                hidden, patient_schemas["book_appointment"]["properties"]
            )
        self.assertNotIn(
            "patient_id",
            patient_schemas["get_patient_appointments"]["properties"],
        )
        self.assertIn(
            "patient_id", staff_schemas["book_appointment"]["properties"]
        )
        self.assertIn(
            "patient_id",
            staff_schemas["get_patient_appointments"]["properties"],
        )


class GraphHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.factory()
        self.patient_user = User(
            full_name="بیمار متصل",
            phone="09121110001",
            password_hash="unused",
            role="patient",
            is_active=True,
        )
        self.other_user = User(
            full_name="بیمار دیگر",
            phone="09121110002",
            password_hash="unused",
            role="patient",
            is_active=True,
        )
        self.db.add_all([self.patient_user, self.other_user])
        await self.db.flush()
        self.patient = Patient(
            national_id="1000000001",
            full_name="بیمار متصل",
            phone="09121110001",
            user_id=self.patient_user.id,
        )
        self.other_patient = Patient(
            national_id="1000000002",
            full_name="بیمار دیگر",
            phone="09121110002",
            user_id=self.other_user.id,
        )
        self.doctor = Doctor(
            full_name="دکتر سارا احمدی",
            specialty="دندانپزشکی عمومی",
            phone="09121110003",
            is_active=True,
        )
        self.service = DentalService(
            name="معاینه اولیه دندانپزشکی",
            description="معاینه و بررسی اولیه دندان و لثه.",
            is_active=True,
        )
        self.doctor.dental_services = [self.service]
        self.db.add_all(
            [self.patient, self.other_patient, self.doctor, self.service]
        )
        await self.db.flush()
        self.linked_appointment = Appointment(
            patient_id=self.patient.id,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_time=datetime(2026, 10, 10, 10),
            status="scheduled",
        )
        self.other_appointment = Appointment(
            patient_id=self.other_patient.id,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_time=datetime(2026, 10, 10, 11),
            status="scheduled",
        )
        self.db.add_all([self.linked_appointment, self.other_appointment])
        self.db.add_all(
            [
                DoctorSchedule(
                    doctor_id=self.doctor.id,
                    day_of_week=0,
                    start_time=time(9),
                    end_time=time(13),
                    slot_duration_minutes=30,
                    is_active=True,
                ),
                DoctorSchedule(
                    doctor_id=self.doctor.id,
                    day_of_week=6,
                    start_time=time(9),
                    end_time=time(13),
                    slot_duration_minutes=30,
                    is_active=True,
                ),
            ]
        )
        await self.db.commit()
        await self.db.refresh(self.linked_appointment)
        await self.db.refresh(self.other_appointment)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _invoke(
        self,
        state,
        model,
        *,
        actor=None,
        session_id="sess-1",
        confirmation=None,
        now=None,
    ):
        context = {
            "db": self.db,
            "llm": model,
            "session_id": session_id,
            "actor": actor or self.patient_user,
            # Fixed Tehran wall-clock time for deterministic slot checks.
            "now": now or datetime(2026, 10, 10, 8, 0),
        }
        if confirmation is not None:
            context["confirmation"] = confirmation
        return await agent_graph.ainvoke(
            state,
            context=context,
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )

    async def test_patient_appointment_read_is_bound_to_linked_patient(self):
        model = ScriptedModel(
            _call(
                "get_patient_appointments",
                {"patient_id": self.other_patient.id},
                "call-read",
            ),
            AIMessage(content="انجام شد."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertEqual(result["last_tool_name"], "get_patient_appointments")
        self.assertTrue(result["last_tool_result"]["ok"])
        rows = result["last_tool_result"]["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["appointment_time"], "10:00")
        self.assertNotIn("appointment_id", rows[0])
        self.assertNotIn("doctor_id", rows[0])
        self.assertNotIn("service_id", rows[0])
        self.assertNotIn("patient_id", rows[0])
        # The forged foreign patient id was ignored in favor of the linked one.
        self.assertNotEqual(rows[0]["appointment_time"], "11:00")

    async def test_patient_booking_ignores_foreign_patient_id(self):
        model = ScriptedModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": self.doctor.id,
                    "service_id": self.service.id,
                    "appointment_date": "1405/08/15",
                    "appointment_time": "09:00",
                    "patient_id": self.other_patient.id,
                },
                "call-book",
            ),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["arguments"]["patient_id"],
            self.patient.id,
        )
        self.assertIn("دکتر سارا احمدی", result["confirmation_prompt"])
        self.assertIn("معاینه اولیه دندانپزشکی", result["confirmation_prompt"])
        self.assertNotIn("بیمار دیگر", result["confirmation_prompt"])

        rejected = await self._invoke(
            result,
            model,
            confirmation={
                "token": result["confirmation_token"],
                "decision": "rejected",
            },
        )
        self.assertFalse(rejected["confirmation_required"])
        self.assertIsNone(rejected["pending_action"])

    async def test_booking_confirmation_rejects_booked_slot_before_token(self):
        model = ScriptedModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": self.doctor.id,
                    "service_id": self.service.id,
                    "appointment_date": "1405/07/18",
                    "appointment_time": "10:00",
                },
                "call-booked-slot",
            ),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertEqual(
            result["last_tool_error"].code, "APPOINTMENT_SLOT_BOOKED"
        )

    async def test_booking_confirmation_rejects_past_slot_before_token(self):
        model = ScriptedModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": self.doctor.id,
                    "service_id": self.service.id,
                    "appointment_date": "1405/08/15",
                    "appointment_time": "09:00",
                },
                "call-past-slot",
            ),
        )
        result = await self._invoke(
            create_initial_state(),
            model,
            now=datetime(2026, 11, 6, 9, 0),
        )
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertEqual(
            result["last_tool_error"].code, "APPOINTMENT_SLOT_IN_PAST"
        )

    async def test_unlinked_patient_is_rejected_before_any_patient_read(self):
        unlinked = User(
            full_name="بدون پرونده",
            phone="09121110009",
            password_hash="unused",
            role="patient",
            is_active=True,
        )
        self.db.add(unlinked)
        await self.db.commit()
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-unlinked"),
            AIMessage(content="حساب شما به پرونده بیمار وصل نیست."),
        )
        result = await self._invoke(
            create_initial_state(), model, actor=unlinked
        )
        self.assertEqual(
            result["last_tool_error"].code, "PATIENT_ACCOUNT_NOT_LINKED"
        )
        self.assertFalse(result["confirmation_required"])
        self.assertEqual(
            result["final_response"], "حساب شما به پرونده بیمار وصل نیست."
        )

    async def test_explicit_step_cap_ends_the_turn_without_a_write(self):
        model = LoopingReadModel()
        result = await self._invoke(create_initial_state(), model)
        self.assertLessEqual(model.calls, MAX_AGENT_STEPS)
        self.assertIn("بیش از حد پیچیده", result["final_response"])
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["pending_action"])
        self.assertEqual(result["route"], "finish")

    async def _add_own_appointment(self, appointment_time):
        async with self.factory() as db:
            appointment = Appointment(
                patient_id=self.patient.id,
                doctor_id=self.doctor.id,
                service_id=self.service.id,
                appointment_time=appointment_time,
                status="scheduled",
            )
            db.add(appointment)
            await db.commit()
            await db.refresh(appointment)
        return appointment

    async def test_patient_cancel_without_internal_id_resolves_own_row(self):
        model = ScriptedModel(
            _call("cancel_appointment", {}, "call-own-cancel"),
            AIMessage(content="نوبت لغو شد."),
        )
        pending = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت من را لغو کن.",
                    }
                ]
            ),
            model,
        )

        self.assertTrue(pending["confirmation_required"])
        self.assertEqual(
            pending["pending_action"]["arguments"]["appointment_id"],
            self.linked_appointment.id,
        )
        prompt = pending["confirmation_prompt"]
        self.assertIn("دکتر سارا احمدی", prompt)
        self.assertIn("معاینه اولیه دندانپزشکی", prompt)
        self.assertNotIn("شماره", prompt)
        self.assertNotRegex(prompt, r"نوبت\s+\d")

        approved = await self._invoke(
            pending,
            model,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertTrue(approved["last_tool_result"]["ok"])
        self.assertNotIn("appointment_id", approved["last_tool_result"]["data"])
        async with self.factory() as db:
            stored = await db.get(Appointment, self.linked_appointment.id)
            await db.refresh(stored)
        self.assertEqual(stored.status, "cancelled")

    async def test_patient_multiple_appointments_without_criteria_require_clarification(self):
        second = await self._add_own_appointment(datetime(2026, 10, 10, 12))
        model = ScriptedModel(_call("cancel_appointment", {}, "call-ambiguous-own"))

        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "لغوش کن."}]
            ),
            model,
        )

        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertIn("چند نوبت", result["final_response"])
        async with self.factory() as db:
            first = await db.get(Appointment, self.linked_appointment.id)
            other = await db.get(Appointment, second.id)
            await db.refresh(first)
            await db.refresh(other)
        self.assertEqual(first.status, "scheduled")
        self.assertEqual(other.status, "scheduled")

    async def test_relative_tomorrow_selects_only_a_real_tomorrow_appointment(self):
        tomorrow = await self._add_own_appointment(datetime(2026, 10, 11, 10))
        model = ScriptedModel(
            _call("cancel_appointment", {}, "call-tomorrow"),
            AIMessage(content="نوبت فردا لغو شد."),
        )

        pending = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردا را لغو کن."}]
            ),
            model,
        )

        self.assertTrue(pending["confirmation_required"])
        self.assertEqual(
            pending["pending_action"]["arguments"]["appointment_id"],
            tomorrow.id,
        )
        async with self.factory() as db:
            today_row = await db.get(Appointment, self.linked_appointment.id)
            tomorrow_row = await db.get(Appointment, tomorrow.id)
            await db.refresh(today_row)
            await db.refresh(tomorrow_row)
        self.assertEqual(today_row.status, "scheduled")
        self.assertEqual(tomorrow_row.status, "scheduled")

    async def test_relative_date_without_matching_appointment_does_not_retarget(self):
        model = ScriptedModel(
            _call("cancel_appointment", {}, "call-no-tomorrow"),
            AIMessage(content="نوبتی برای فردا پیدا نشد."),
        )

        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردا را لغو کن."}]
            ),
            model,
        )

        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertIn("پیدا نشد", result["final_response"])
        async with self.factory() as db:
            stored = await db.get(Appointment, self.linked_appointment.id)
            await db.refresh(stored)
        self.assertEqual(stored.status, "scheduled")

    async def test_cancel_confirmation_uses_names_and_current_slot_data(self):
        model = ScriptedModel(
            _call(
                "cancel_appointment",
                {"appointment_id": self.linked_appointment.id},
                "call-cancel",
            ),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertTrue(result["confirmation_required"])
        prompt = result["confirmation_prompt"]
        jalali_date, jalali_time = gregorian_to_jalali(
            self.linked_appointment.appointment_time
        )
        self.assertIn("لغو نوبت", prompt)
        self.assertNotIn("شماره", prompt)
        self.assertNotRegex(prompt, r"نوبت\s+\d")
        self.assertIn("دکتر سارا احمدی", prompt)
        self.assertIn("معاینه اولیه دندانپزشکی", prompt)
        self.assertIn(to_persian_digits(jalali_date), prompt)
        self.assertIn(to_persian_digits(jalali_time), prompt)

    async def test_patient_reschedule_without_internal_id_resolves_source_from_text(self):
        # The reschedule service validates the new slot against the real clinic
        # clock, so derive the next scheduled day (Friday/Saturday) instead of
        # pinning a fixed date that eventually becomes the past.
        # The fixture schedules the doctor on Saturday (weekday 5) and Friday
        # (weekday 4), matching the clinic's Saturday-based week.
        real_now = datetime.now(ZoneInfo("Asia/Tehran"))
        days_ahead = 1
        while (real_now + timedelta(days=days_ahead)).weekday() not in (4, 5):
            days_ahead += 1
        target_day = (real_now + timedelta(days=days_ahead)).date()
        target_datetime = datetime.combine(target_day, time(9))
        target_date, _ = gregorian_to_jalali(target_datetime)

        model = ScriptedModel(
            _call(
                "reschedule_appointment",
                {
                    "appointment_date": target_date,
                    "appointment_time": "09:00",
                },
                "call-own-reschedule",
            ),
            AIMessage(content="نوبت منتقل شد."),
        )

        pending = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "نوبت امروز ساعت 10:00 را به "
                            f"{target_date} ساعت 09:00 منتقل کن."
                        ),
                    }
                ]
            ),
            model,
        )

        self.assertTrue(
            pending["confirmation_required"],
            pending.get("last_tool_error"),
        )
        self.assertEqual(
            pending["pending_action"]["arguments"]["appointment_id"],
            self.linked_appointment.id,
        )
        self.assertNotIn("appointment_id", pending["confirmation_prompt"])

        approved = await self._invoke(
            pending,
            model,
            confirmation={
                "token": pending["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertTrue(
            approved["last_tool_result"]["ok"],
            approved["last_tool_result"].get("error"),
        )
        async with self.factory() as db:
            stored = await db.get(Appointment, self.linked_appointment.id)
            await db.refresh(stored)
        self.assertEqual(stored.appointment_time, target_datetime)

    async def test_staff_may_authorize_booking_for_a_new_patient(self):
        receptionist = User(
            full_name="پذیرش",
            phone="09121110010",
            password_hash="unused",
            role="receptionist",
            is_active=True,
        )
        self.db.add(receptionist)
        await self.db.commit()
        await authorize_tool_call(
            self.db,
            receptionist,
            "book_appointment",
            {
                "doctor_id": self.doctor.id,
                "service_id": self.service.id,
                "appointment_date": "1405/08/15",
                "appointment_time": "09:00",
                "national_id": "1000000099",
                "full_name": "بیمار جدید",
                "phone": "09121110011",
            },
        )

    async def test_patient_cannot_cancel_another_patients_appointment(self):
        model = ScriptedModel(
            _call(
                "cancel_appointment",
                {"appointment_id": self.other_appointment.id},
                "call-foreign-cancel",
            ),
            AIMessage(content="این عملیات مجاز نیست."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertEqual(result["last_tool_error"].code, "COMMON_FORBIDDEN")
        self.assertNotIn("بیمار دیگر", result["final_response"])

    async def test_patient_cannot_reschedule_another_patients_appointment(self):
        model = ScriptedModel(
            _call(
                "reschedule_appointment",
                {
                    "appointment_id": self.other_appointment.id,
                    "appointment_date": "1405/08/15",
                    "appointment_time": "09:00",
                },
                "call-foreign-reschedule",
            ),
            AIMessage(content="این عملیات مجاز نیست."),
        )
        result = await self._invoke(create_initial_state(), model)
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["confirmation_token"])
        self.assertIsNone(result["pending_action"])
        self.assertEqual(result["last_tool_error"].code, "COMMON_FORBIDDEN")
        self.assertNotIn("بیمار دیگر", result["final_response"])


if __name__ == "__main__":
    unittest.main()
