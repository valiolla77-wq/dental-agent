"""Regression tests for the post-P1 eval failure patterns.

Covers the four patterns left after the balanced-plan fixes (see
``eval-rerun-report.md``):

1. Picked-option -> booking mismatch (A03/A08): merged turn option sets,
   requested-time anchoring, and the booking-criteria confirmation guard.
2. Cancel/reschedule stalls (B01/B02/B06): server stall directives that
   re-ask the model when it ends a turn with words instead of the write.
   Round 5: when the model answers every re-ask with nothing, the
   server builds the confirmation proposal itself from the fetched rows
   (ServerProposalTests) instead of ending on a clarification.
3. Conversational booking stalls (C04/C06): the same directive mechanism
   for search-then-promise and no-tool booking requests.
4. Edge criteria (B04/B05): explicit rejection for past targets and
   fetch-before-reject.
"""

import json
import os
import unittest
from datetime import datetime, time

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32-chars-long")
os.environ.setdefault(
    "CONFIRMATION_HMAC_SECRET",
    "test-confirmation-hmac-secret-32-chars-long",
)
os.environ.setdefault("CONFIRMATION_TTL_SECONDS", "300")

from langchain_core.messages import AIMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent import agent_graph, create_initial_state
from app.agent.appointment_selection import (
    AMBIGUOUS_SELECTION_MESSAGE,
    BOOKING_MISMATCH_MESSAGE,
    PAST_DESTINATION_MESSAGE,
    PAST_TARGET_MESSAGE,
    _GENERIC_DOCTOR_TOKENS,
    _GENERIC_SERVICE_TOKENS,
    _name_matches,
    booking_criteria_mismatch,
    parse_reschedule_destination,
    resolve_appointment_target,
)
from app.agent.graph import AGENT_RECURSION_LIMIT
from app.agent.options import (
    anchor_requested_time,
    booking_args_for_option,
    build_merged_slot_options,
)
from app.models.agent_confirmation import AgentConfirmation
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.user import User
from app.routers.agent_chat import _turn_active_options


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
        self.calls = 0

    def bind_tools(self, schemas):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        self.received.append(list(messages))
        return self.responses.pop(0)

    def saw_directive(self, stage):
        marker = f"[server-directive:{stage}]"
        return any(
            getattr(message, "content", "")
            and marker in str(message.content)
            for call in self.received
            for message in call
        )


class _Fixture(unittest.IsolatedAsyncioTestCase):
    """Patient + two doctors + three services on an in-memory database."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.db = self.factory()
        self.patient_user = User(
            full_name="بیمار آزمون",
            phone="09121110001",
            password_hash="unused",
            role="patient",
            is_active=True,
        )
        self.db.add(self.patient_user)
        await self.db.flush()
        self.patient = Patient(
            national_id="1000000001",
            full_name="بیمار آزمون",
            phone="09121110001",
            user_id=self.patient_user.id,
        )
        self.doctor_a = Doctor(
            full_name="دکتر سارا احمدی",
            specialty="دندانپزشکی عمومی",
            phone="09121110003",
            is_active=True,
        )
        self.doctor_b = Doctor(
            full_name="دکتر امیر کریمی",
            specialty="دندانپزشکی عمومی",
            phone="09121110004",
            is_active=True,
        )
        self.exam = DentalService(
            name="معاینه اولیه دندانپزشکی",
            description="معاینه و بررسی اولیه.",
            is_active=True,
        )
        self.filling = DentalService(
            name="ترمیم دندان",
            description="ترمیم و پر کردن دندان.",
            is_active=True,
        )
        self.scaling = DentalService(
            name="جرم‌گیری و پاکسازی",
            description="جرم‌گیری و پاکسازی دندان‌ها.",
            is_active=True,
        )
        self.doctor_a.dental_services = [self.exam, self.filling, self.scaling]
        self.doctor_b.dental_services = [self.exam, self.filling, self.scaling]
        self.db.add_all(
            [
                self.patient,
                self.doctor_a,
                self.doctor_b,
                self.exam,
                self.filling,
                self.scaling,
            ]
        )
        await self.db.flush()
        # Saturday-based schedule days: 0 = Saturday, 6 = Friday.
        for day in (0, 6):
            self.db.add(
                DoctorSchedule(
                    doctor_id=self.doctor_a.id,
                    day_of_week=day,
                    start_time=time(9),
                    end_time=time(13),
                    slot_duration_minutes=30,
                    is_active=True,
                )
            )
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _add_appointment(self, when, doctor, service):
        appointment = Appointment(
            patient_id=self.patient.id,
            doctor_id=doctor.id,
            service_id=service.id,
            appointment_time=when,
            status="scheduled",
        )
        self.db.add(appointment)
        await self.db.commit()
        await self.db.refresh(appointment)
        return appointment

    async def _invoke(self, state, model, *, now=None, confirmation=None):
        context = {
            "db": self.db,
            "llm": model,
            "session_id": "sess-regression",
            "actor": self.patient_user,
            "now": now or datetime(2026, 10, 10, 8, 0),
        }
        if confirmation is not None:
            context["confirmation"] = confirmation
        return await agent_graph.ainvoke(
            state,
            context=context,
            config={"recursion_limit": AGENT_RECURSION_LIMIT},
        )


class StallDirectiveGraphTests(_Fixture):
    async def test_b01_stalled_cancel_is_nudged_into_confirmation(self):
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(
                content=(
                    "شما یک نوبت معاینه با دکتر سارا احمدی برای فردا ساعت "
                    "۱۰:۰۰ دارید. آیا می‌خواهید این نوبت لغو شود؟"
                )
            ),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "cancel_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )

    async def test_b05_rejection_happens_only_after_fetching(self):
        await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        rejection = "نمی‌توانم نوبت را به گذشته منتقل کنم."
        model = ScriptedModel(
            AIMessage(content=rejection),
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=rejection),
            AIMessage(content=rejection),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت فردام رو بنداز دیروز ساعت ۹.",
                    }
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("fetch-first"))
        tool_names = [
            message.get("name")
            for message in result["messages"]
            if message.get("role") == "tool"
        ]
        self.assertIn("get_patient_appointments", tool_names)
        self.assertFalse(result["confirmation_required"])
        self.assertIn("گذشته", result["final_response"])

    async def test_c06_booking_without_service_uses_default_flow(self):
        model = ScriptedModel(
            AIMessage(content="برای چه خدمتی نوبت می‌خواهید؟"),
            _call("search_dental_services", {"query": "معاینه"}, "call-search"),
            _call(
                "find_nearest_appointments",
                {"service_id": self.exam.id},
                "call-nearest",
            ),
            AIMessage(content="نزدیک‌ترین نوبت‌های معاینه را پیدا کردم."),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {"role": "user", "content": "بیمهٔ تکمیلی دارم، نوبت می‌خوام."}
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("book-default"))
        tool_names = [
            message.get("name")
            for message in result["messages"]
            if message.get("role") == "tool"
        ]
        self.assertIn("find_nearest_appointments", tool_names)
        self.assertEqual(
            result["final_response"], "نزدیک‌ترین نوبت‌های معاینه را پیدا کردم."
        )

    async def test_c04_search_promise_is_nudged_to_slots(self):
        model = ScriptedModel(
            _call("search_dental_services", {"query": "معاینه"}, "call-search"),
            AIMessage(
                content=(
                    "برای معاینه اولیه دندانپزشکی، نزدیک‌ترین نوبت‌ها را "
                    "برات پیدا می‌کنم."
                )
            ),
            _call(
                "find_nearest_appointments",
                {"service_id": self.exam.id},
                "call-nearest",
            ),
            AIMessage(content="این ساعت‌های آزاد معاینه است."),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "سلام میخام نوبت بگیرم برای معاینه",
                    }
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("slots-now"))
        tool_names = [
            message.get("name")
            for message in result["messages"]
            if message.get("role") == "tool"
        ]
        self.assertIn("find_nearest_appointments", tool_names)

    async def test_plain_answer_without_intent_is_not_nudged(self):
        model = ScriptedModel(AIMessage(content="ساعت کاری کلینیک ۹ تا ۱۳ است."))
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "ساعت کاری کلینیک چیه؟"}]
            ),
            model,
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(
            result["final_response"], "ساعت کاری کلینیک ۹ تا ۱۳ است."
        )


class BookingGuardGraphTests(_Fixture):
    async def test_model_booking_contradicting_named_service_is_blocked(self):
        model = ScriptedModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": self.doctor_b.id,
                    "service_id": self.filling.id,
                    "appointment_date": "1405/08/15",
                    "appointment_time": "09:00",
                },
                "call-book-wrong",
            ),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "جرم‌گیری می‌خوام، شنبهٔ آینده ساعت صبح باشه.",
                    }
                ]
            ),
            model,
        )
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result["pending_action"])
        self.assertEqual(result["final_response"], BOOKING_MISMATCH_MESSAGE)

    async def test_model_booking_matching_named_service_is_confirmed(self):
        model = ScriptedModel(
            _call(
                "book_appointment",
                {
                    "doctor_id": self.doctor_a.id,
                    "service_id": self.exam.id,
                    "appointment_date": "1405/08/15",
                    "appointment_time": "09:00",
                },
                "call-book-ok",
            ),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "معاینه می‌خوام."}]
            ),
            model,
        )
        self.assertTrue(result["confirmation_required"])
        self.assertIn("معاینه اولیه دندانپزشکی", result["confirmation_prompt"])

    async def test_host_resolved_booking_skips_guard(self):
        # The deterministic option path already binds the booking to the
        # displayed option set, so the guard must not second-guess it even
        # when the raw request named another service.
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "جرم‌گیری می‌خوام، شنبهٔ آینده ساعت صبح باشه.",
                    }
                ],
                requested_tool="book_appointment",
                tool_arguments={
                    "doctor_id": self.doctor_a.id,
                    "service_id": self.filling.id,
                    "appointment_date": "1405/08/15",
                    "appointment_time": "09:00",
                },
            ),
            ScriptedModel(),
        )
        self.assertTrue(result["confirmation_required"])
        self.assertIn("ترمیم دندان", result["confirmation_prompt"])


class BookingCriteriaMismatchTests(_Fixture):
    async def test_named_time_mismatch_is_blocked(self):
        mismatch = await booking_criteria_mismatch(
            self.db,
            arguments={
                "doctor_id": self.doctor_a.id,
                "service_id": self.filling.id,
                "appointment_date": "1405/09/03",
                "appointment_time": "09:00",
            },
            user_texts=["می‌خوام فردا ساعت ۱۰ پیش دکتر سارا احمدی ترمیم بگیرم."],
            now=datetime(2026, 11, 23, 12, 0),
        )
        self.assertEqual(mismatch, BOOKING_MISMATCH_MESSAGE)

    async def test_named_time_match_passes(self):
        mismatch = await booking_criteria_mismatch(
            self.db,
            arguments={
                "doctor_id": self.doctor_a.id,
                "service_id": self.filling.id,
                "appointment_date": "1405/09/03",
                "appointment_time": "10:00",
            },
            user_texts=["می‌خوام فردا ساعت ۱۰ پیش دکتر سارا احمدی ترمیم بگیرم."],
            now=datetime(2026, 11, 23, 12, 0),
        )
        self.assertIsNone(mismatch)

    async def test_assistant_offered_alternative_is_accepted(self):
        mismatch = await booking_criteria_mismatch(
            self.db,
            arguments={
                "doctor_id": self.doctor_a.id,
                "service_id": self.filling.id,
                "appointment_date": "1405/09/03",
                "appointment_time": "09:00",
            },
            user_texts=["می‌خوام فردا ساعت ۱۰ پیش دکتر سارا احمدی ترمیم بگیرم."],
            now=datetime(2026, 11, 23, 12, 0),
            last_assistant_text="ساعت ۱۰ پر است؛ ساعت ۹:۰۰ آزاد است، ثبت کنم؟",
        )
        self.assertIsNone(mismatch)

    async def test_named_doctor_mismatch_is_blocked(self):
        mismatch = await booking_criteria_mismatch(
            self.db,
            arguments={
                "doctor_id": self.doctor_a.id,
                "service_id": self.filling.id,
                "appointment_date": "1405/09/03",
                "appointment_time": "10:00",
            },
            user_texts=["پیش دکتر امیر کریمی ترمیم می‌خوام."],
            now=datetime(2026, 11, 23, 12, 0),
        )
        self.assertEqual(mismatch, BOOKING_MISMATCH_MESSAGE)


class PossessiveServiceMatchTests(unittest.TestCase):
    """Eval B02: a possessive suffix must not defeat service matching.

    «ترمیمم» is «ترمیم» + possessive ـم, but the old word-boundary
    pattern ``(?<!\\w)ترمیم(?!\\w)`` rejected it, so the service filter
    never engaged and every cancel/reschedule with several future
    appointments came back AMBIGUOUS.
    """

    def test_all_possessive_suffixes_match(self):
        for text in (
            "ترمیمم",
            "ترمیمت",
            "ترمیمش",
            "ترمیممان",
            "ترمیم‌تان",
            "ترمیمشان",
        ):
            with self.subTest(text=text):
                self.assertTrue(
                    _name_matches(
                        text,
                        "ترمیم دندان",
                        _GENERIC_SERVICE_TOKENS,
                        allow_possessive=True,
                    )
                )

    def test_zwnj_joined_suffix_matches(self):
        # «جرم‌گیریم»: after normalization the ZWNJ becomes a space, so
        # the token after it («گیری») carries the attached ـم.
        self.assertTrue(
            _name_matches(
                "جرم‌گیریم",
                "جرم‌گیری و پاکسازی",
                _GENERIC_SERVICE_TOKENS,
                allow_possessive=True,
            )
        )
        # Isolated: only the suffixed token can match here.
        self.assertTrue(
            _name_matches(
                "جرم‌گیریم",
                "گیری",
                _GENERIC_SERVICE_TOKENS,
                allow_possessive=True,
            )
        )

    def test_other_service_does_not_match(self):
        self.assertFalse(
            _name_matches(
                "ترمیمم",
                "جرم‌گیری و پاکسازی",
                _GENERIC_SERVICE_TOKENS,
                allow_possessive=True,
            )
        )

    def test_non_possessive_continuations_still_rejected(self):
        for text in ("ترمیمی", "ترمیمات"):
            with self.subTest(text=text):
                self.assertFalse(
                    _name_matches(
                        text,
                        "ترمیم دندان",
                        _GENERIC_SERVICE_TOKENS,
                        allow_possessive=True,
                    )
                )

    def test_doctor_matching_stays_strict(self):
        # Minimal scope: possessive acceptance is service-only. Doctor
        # names keep the old strict boundary.
        self.assertFalse(
            _name_matches(
                "احمدیم", "دکتر سارا احمدی", _GENERIC_DOCTOR_TOKENS
            )
        )
        self.assertFalse(
            _name_matches(
                "ترمیمم",
                "ترمیم دندان",
                _GENERIC_SERVICE_TOKENS,
            )
        )


class PastTargetSelectionTests(_Fixture):
    NOW = datetime(2026, 11, 23, 12, 0)

    async def _resolve(self, text):
        return await resolve_appointment_target(
            self.db,
            appointment_id=None,
            user_text=text,
            patient_ids=[self.patient.id],
            now=self.NOW,
        )

    async def test_yesterday_request_is_rejected_explicitly(self):
        await self._add_appointment(
            datetime(2026, 11, 22, 9, 30), self.doctor_a, self.scaling
        )
        await self._add_appointment(
            datetime(2026, 11, 22, 9, 30), self.doctor_b, self.scaling
        )
        selection = await self._resolve("نوبت دیروزم رو لغو کن.")
        self.assertIsNone(selection.appointment)
        self.assertEqual(selection.clarification, PAST_TARGET_MESSAGE)

    async def test_past_rows_do_not_make_future_target_ambiguous(self):
        await self._add_appointment(
            datetime(2026, 11, 21, 9, 0), self.doctor_b, self.filling
        )
        future = await self._add_appointment(
            datetime(2026, 11, 25, 11, 0), self.doctor_a, self.filling
        )
        selection = await self._resolve("نوبت ترمیمم رو لغو کن.")
        self.assertIsNotNone(selection.appointment)
        self.assertEqual(selection.appointment.id, future.id)
        self.assertIsNone(selection.clarification)

    async def test_two_past_matches_without_date_stay_ambiguous(self):
        await self._add_appointment(
            datetime(2026, 11, 22, 9, 30), self.doctor_a, self.scaling
        )
        await self._add_appointment(
            datetime(2026, 11, 22, 9, 30), self.doctor_b, self.scaling
        )
        selection = await self._resolve("نوبت جرم‌گیری‌م رو لغو کن.")
        self.assertIsNone(selection.appointment)
        self.assertEqual(selection.clarification, AMBIGUOUS_SELECTION_MESSAGE)

    async def test_tomorrow_request_still_resolves(self):
        target = await self._add_appointment(
            datetime(2026, 11, 24, 9, 0), self.doctor_a, self.exam
        )
        selection = await self._resolve("نوبت فردام رو لغو کن.")
        self.assertIsNotNone(selection.appointment)
        self.assertEqual(selection.appointment.id, target.id)


class PossessiveTargetResolutionTests(_Fixture):
    """B02 resolves once the service filter engages; B06 stays refused."""

    NOW = datetime(2026, 11, 25, 12, 20)

    async def _resolve(self, text):
        return await resolve_appointment_target(
            self.db,
            appointment_id=None,
            user_text=text,
            patient_ids=[self.patient.id],
            now=self.NOW,
        )

    async def test_b02_possessive_filling_resolves_to_single_future(self):
        target = await self._add_appointment(
            datetime(2026, 11, 26, 9, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 11, 27, 10, 0), self.doctor_b, self.scaling
        )
        selection = await self._resolve("نوبت ترمیمم رو لغو کن.")
        self.assertIsNotNone(selection.appointment)
        self.assertEqual(selection.appointment.id, target.id)
        self.assertIsNone(selection.clarification)

    async def test_b02_still_ambiguous_with_two_future_fillings(self):
        # The fix narrows by service; it must not invent a unique target
        # when two future ترمیم appointments remain. In eval4 this is the
        # state before B01 cancels its row, so B02 only resolves after B01.
        await self._add_appointment(
            datetime(2026, 11, 26, 9, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 11, 28, 9, 0), self.doctor_b, self.filling
        )
        selection = await self._resolve("نوبت ترمیمم رو لغو کن.")
        self.assertIsNone(selection.appointment)
        self.assertEqual(
            selection.clarification, AMBIGUOUS_SELECTION_MESSAGE
        )

    async def test_b06_simultaneous_scaling_stays_ambiguous(self):
        # B06-style: two جرم‌گیری at the identical date/time with
        # different doctors. The guard must refuse with a structured
        # clarification — no guess, no write.
        await self._add_appointment(
            datetime(2026, 11, 29, 9, 0), self.doctor_a, self.scaling
        )
        await self._add_appointment(
            datetime(2026, 11, 29, 9, 0), self.doctor_b, self.scaling
        )
        selection = await self._resolve("نوبت جرم‌گیری‌م رو لغو کن.")
        self.assertIsNone(selection.appointment)
        self.assertEqual(
            selection.clarification, AMBIGUOUS_SELECTION_MESSAGE
        )


def _slots_event(doctor_id, service_id, date, times):
    return (
        "find_available_slots",
        {
            "ok": True,
            "data": {
                "doctor_id": doctor_id,
                "service_id": service_id,
                "appointment_date": date,
                "available_slots": times,
            },
            "error": None,
        },
    )


def _tool_message(name, result):
    return {
        "role": "tool",
        "name": name,
        "tool_call_id": f"call-{name}",
        "content": json.dumps(result, ensure_ascii=False),
    }


class MergedOptionsTests(unittest.TestCase):
    def test_two_slot_calls_merge_in_call_order(self):
        merged = build_merged_slot_options(
            [
                _slots_event(1, 3, "1405/09/07", ["09:00", "09:30"]),
                _slots_event(2, 2, "1405/09/07", ["09:00"]),
            ]
        )
        self.assertIsNotNone(merged)
        kind, payload = merged
        self.assertEqual(kind, "appointment")
        items = payload["items"]
        self.assertEqual(
            [
                (item["doctor_id"], item["service_id"], item["appointment_time"])
                for item in items
            ],
            [(1, 3, "09:00"), (1, 3, "09:30"), (2, 2, "09:00")],
        )
        # A03's pick: «۱» must book exactly the first displayed option.
        args = booking_args_for_option(kind, payload, items[0], 5)
        self.assertEqual(
            args,
            {
                "patient_id": 5,
                "doctor_id": 1,
                "service_id": 3,
                "appointment_date": "1405/09/07",
                "appointment_time": "09:00",
            },
        )

    def test_anchor_moves_requested_time_first(self):
        payload = {
            "items": [
                {"kind": "slot_time", "time": "09:00"},
                {"kind": "slot_time", "time": "09:30"},
                {"kind": "slot_time", "time": "10:00"},
            ]
        }
        anchored = anchor_requested_time("slot_time", payload, {"10:00"})
        self.assertEqual(anchored["items"][0]["time"], "10:00")
        unchanged = anchor_requested_time(
            "slot_time", payload, {"10:00", "09:00"}
        )
        self.assertEqual(unchanged["items"][0]["time"], "09:00")

    def test_turn_options_merge_multiple_slot_calls(self):
        slots_a = {
            "doctor_id": 1,
            "service_id": 3,
            "appointment_date": "1405/09/07",
            "available_slots": ["09:00", "09:30"],
        }
        slots_b = {
            "doctor_id": 2,
            "service_id": 2,
            "appointment_date": "1405/09/07",
            "available_slots": ["09:00"],
        }
        result = {
            "last_tool_name": "find_available_slots",
            "last_tool_result": {"ok": True, "data": slots_b, "error": None},
            "messages": [
                {"role": "user", "content": "جرم‌گیری می‌خوام، شنبهٔ آینده."},
                _tool_message(
                    "find_available_slots",
                    {"ok": True, "data": slots_a, "error": None},
                ),
                _tool_message(
                    "find_available_slots",
                    {"ok": True, "data": slots_b, "error": None},
                ),
            ],
        }
        kind, payload = _turn_active_options(result)
        self.assertEqual(kind, "appointment")
        self.assertEqual(len(payload["items"]), 3)
        self.assertEqual(payload["items"][0]["doctor_id"], 1)

    def test_turn_options_single_slot_call_keeps_shape_and_anchors(self):
        slots = {
            "doctor_id": 1,
            "service_id": 2,
            "appointment_date": "1405/09/03",
            "available_slots": ["09:00", "09:30", "10:00"],
        }
        result = {
            "last_tool_name": "find_available_slots",
            "last_tool_result": {"ok": True, "data": slots, "error": None},
            "messages": [
                {"role": "user", "content": "فردا ساعت ۱۰ ترمیم می‌خوام."},
                _tool_message(
                    "find_available_slots",
                    {"ok": True, "data": slots, "error": None},
                ),
            ],
        }
        kind, payload = _turn_active_options(
            result, requested_times={"10:00"}
        )
        self.assertEqual(kind, "slot_time")
        self.assertEqual(payload["items"][0]["time"], "10:00")
        kind, payload = _turn_active_options(result)
        self.assertEqual(kind, "slot_time")
        self.assertEqual(payload["items"][0]["time"], "09:00")


FALLBACK_TEXT = "متوجه درخواست نشدم؛ لطفاً آن را واضح‌تر بیان کنید."


def _invalid_call(name="cancel_appointment"):
    """A model response whose only tool call failed argument parsing.

    Through the OpenAI-compatible provider proxy this is how a real call
    arrives when its argument JSON is malformed: LangChain parks it in
    ``invalid_tool_calls`` and ``tool_calls`` stays empty, so response
    interpretation sees neither a usable call nor any text.
    """
    return AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": name,
                "args": "{}",
                "id": "bad-call",
                "error": "Function call arguments are not valid JSON",
            }
        ],
    )


def _repeated_list_text():
    """The eval-B02 degenerate reply: one fetched row looped verbatim."""
    line = "- نوبت با دکتر سارا احمدی در تاریخ 1405/07/25 ساعت 10:00"
    return "\n" + "\n".join([line] * 6)


class LiveFailureShapeTests(_Fixture):
    """Regression tests for the eval3 live failures (B01/B02).

    The earlier stall tests simulated a *verbose text question* and a
    perfectly-formed recovery call. Live, Gemini stalled differently:
    empty/unparseable responses (B01) and a degenerate repeated list
    (B02). These tests script those exact shapes.

    Round 3 (24 Nov) added two more: a *whitespace-only* reply (``"\\n"``,
    truthy, so it slipped past the empty-finish guard) and a model that
    answers the act-now directive with *another free-text question*
    (B01), plus empty retries that also came back empty (B02/B04/B05/
    B06) and left only the bare fallback. The tests below script those
    shapes too.
    """

    async def test_b01_empty_reply_after_fetch_still_confirms(self):
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertNotIn("متوجه درخواست نشدم", result["final_response"])

    async def test_b01_two_empty_replies_after_fetch_are_recovered(self):
        # The live shape: the act-now re-ask ALSO came back empty, the
        # stage was spent, and the fallback surfaced. The empty finish
        # must earn one more ask with the same directive.
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertNotIn("متوجه درخواست نشدم", result["final_response"])

    async def test_b01_malformed_call_is_logged_and_recovered(self):
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            _invalid_call(),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        with self.assertLogs("dental_agent.agent", level="WARNING") as logs:
            result = await self._invoke(
                create_initial_state(
                    messages=[
                        {"role": "user", "content": "نوبت فردام رو لغو کن."}
                    ]
                ),
                model,
            )
        self.assertTrue(
            any(
                "invalid" in record.lower()
                and "cancel_appointment" in record
                for record in logs.output
            ),
            logs.output,
        )
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )

    async def test_b01_two_malformed_calls_are_recovered(self):
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            _invalid_call(),
            _invalid_call(),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertNotIn("متوجه درخواست نشدم", result["final_response"])

    async def test_empty_reply_without_intent_is_not_retried(self):
        model = ScriptedModel(AIMessage(content=""))
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "سلام، خوبی؟"}]
            ),
            model,
        )
        self.assertEqual(model.calls, 1)
        self.assertEqual(result["final_response"], FALLBACK_TEXT)

    async def test_b02_repeated_list_then_cooperates_confirms(self):
        target = await self._add_appointment(
            datetime(2026, 10, 17, 10, 0), self.doctor_a, self.filling
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=_repeated_list_text()),
            AIMessage(content=_repeated_list_text()),
            _call(
                "reschedule_appointment",
                {"appointment_date": "1405/07/25", "appointment_time": "11:00"},
                "call-reschedule",
            ),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت ترمیمم رو بنداز شنبهٔ آینده ساعت ۱۱.",
                    }
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertTrue(model.saw_directive("act-now-repeat"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "reschedule_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )

    async def test_b02_possessive_service_filter_disambiguates(self):
        # Eval B02, live phrasing, with two future appointments of
        # different services (ترمیم and معاینه). Before the
        # possessive-suffix fix the service filter never engaged, the
        # target stayed AMBIGUOUS and no confirmation could ever issue —
        # even when the model cooperated immediately.
        target = await self._add_appointment(
            datetime(2026, 10, 17, 10, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 10, 18, 9, 0), self.doctor_b, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            _call(
                "reschedule_appointment",
                {"appointment_date": "1405/07/25", "appointment_time": "11:00"},
                "call-reschedule",
            ),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت ترمیمم رو بنداز شنبهٔ آینده ساعت ۱۱.",
                    }
                ]
            ),
            model,
        )
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "reschedule_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )

    async def test_b02_never_cooperates_gets_server_proposal(self):
        # Round 5: the model never cooperates (three degenerate lists),
        # but the target is unique and the destination is parseable and
        # free, so the server builds the confirmation proposal itself
        # instead of ending on a clarification. This replaces the
        # round-4 expectation (server clarification) for the unique-target
        # shape; the ambiguous shape still gets a clarification (see
        # ServerProposalTests).
        target = await self._add_appointment(
            datetime(2026, 10, 17, 10, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 10, 12, 9, 0), self.doctor_b, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=_repeated_list_text()),
            AIMessage(content=_repeated_list_text()),
            AIMessage(content=_repeated_list_text()),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت ترمیمم رو بنداز شنبهٔ آینده ساعت ۱۱.",
                    }
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now-repeat"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "reschedule_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_date"],
            "1405/07/25",
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_time"], "11:00"
        )
        self.assertIn("جابه‌جایی", result["final_response"])

    async def test_b02_whitespace_only_reply_after_fetch_still_confirms(self):
        # Live round-3 B02: the reply was exactly "\\n". It is truthy, so
        # the old ``not final_response`` guard treated it as a real reply
        # and no retry ever fired. A whitespace-only finish is an empty
        # finish and must earn the same recovery as "".
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content="\n"),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertNotIn("متوجه درخواست نشدم", result["final_response"])

    async def test_empty_retry_also_empty_gets_server_proposal(self):
        # Live round-3 B02/B04/B05/B06: the extra re-ask for an empty
        # finish also came back empty. Round 5: with a unique target the
        # turn now ends on a server-built confirmation proposal, never
        # the bare fallback and never a clarification that asks the user
        # to repeat what they already said. (The ambiguous-target shape
        # still ends on a server-built clarification; see
        # ServerProposalTests.)
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertEqual(model.calls, 4)
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "cancel_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        final = result["final_response"]
        self.assertNotEqual(final, FALLBACK_TEXT)
        self.assertNotIn("متوجه درخواست نشدم", final)
        self.assertIn("لغو نوبت", final)

    async def test_b01_repeated_question_is_nudged_into_confirmation(self):
        # Live round-3 B01: the model answered the act-now directive with
        # another free-text question instead of the write. The second
        # question must fire the act-now-question stage, and a cooperating
        # model then issues the confirmation proposal.
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        question = (
            "شما یک نوبت معاینه با دکتر سارا احمدی برای فردا ساعت "
            "۱۰:۰۰ دارید. آیا می‌خواهید این نوبت لغو شود؟"
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=question),
            AIMessage(content=question),
            _call("cancel_appointment", {}, "call-cancel"),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertTrue(model.saw_directive("act-now-question"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "cancel_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertNotIn("متوجه درخواست نشدم", result["final_response"])

    async def test_b06_ambiguous_target_is_not_guessed(self):
        # B06 control: two simultaneous جرم‌گیری appointments (same
        # date/time, different doctors). A disambiguation question naming
        # both doctors is legitimate: the act-now-question stage must not
        # fire, no confirmation may be issued, and the turn ends on the
        # question — the ambiguity guard is never bypassed.
        await self._add_appointment(
            datetime(2026, 10, 17, 9, 30), self.doctor_a, self.scaling
        )
        await self._add_appointment(
            datetime(2026, 10, 17, 9, 30), self.doctor_b, self.scaling
        )
        question = (
            "دو نوبت جرم‌گیری دارید: دکتر سارا احمدی و دکتر امیر کریمی، "
            "هر دو شنبه ساعت ۰۹:۳۰. کدام نوبت را لغو کنم؟"
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=question),
            AIMessage(content=question),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {"role": "user", "content": "نوبت جرم‌گیریم رو لغو کن."}
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertFalse(model.saw_directive("act-now-question"))
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result.get("pending_action"))
        self.assertEqual(result["final_response"], question)

    async def test_legit_question_after_act_now_is_not_replaced(self):
        await self._add_appointment(
            datetime(2026, 10, 17, 10, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 10, 18, 10, 0), self.doctor_b, self.filling
        )
        question = (
            "دو نوبت ترمیم دارید: دکتر سارا احمدی شنبه ساعت ۱۰:۰۰ و "
            "دکتر امیر کریمی یکشنبه ساعت ۱۰:۰۰. کدام نوبت را جابه‌جا کنم؟"
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=question),
            AIMessage(content=question),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت ترمیمم رو بنداز شنبهٔ آینده ساعت ۱۱.",
                    }
                ]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertFalse(model.saw_directive("act-now-repeat"))
        self.assertEqual(result["final_response"], question)


class ServerProposalTests(_Fixture):
    """Round 5: the server builds the confirmation proposal itself.

    When the model stalls after fetching — empty, whitespace, repeated
    list, or another free-text question on every re-ask — the graph no
    longer ends on a clarification for a uniquely identified target: it
    proposes the cancel/reschedule through the normal confirmation
    gate. The guards stay in place: ambiguous targets are never
    guessed, past targets and past destinations are explicitly
    rejected, and nothing executes without the one-time user approval.
    """

    async def test_stalled_question_cancel_gets_server_proposal(self):
        # B01 live shape, model never cooperates: the yes/no question
        # comes back after both the act-now and act-now-question stages.
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        question = (
            "شما یک نوبت معاینه با دکتر سارا احمدی برای فردا ساعت "
            "۱۰:۰۰ دارید. آیا می‌خواهید این نوبت لغو شود؟"
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=question),
            AIMessage(content=question),
            AIMessage(content=question),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(model.saw_directive("act-now"))
        self.assertTrue(model.saw_directive("act-now-question"))
        self.assertTrue(result["confirmation_required"])
        self.assertEqual(
            result["pending_action"]["tool_name"], "cancel_appointment"
        )
        self.assertEqual(
            result["pending_action"]["arguments"]["appointment_id"], target.id
        )
        self.assertIn("لغو نوبت", result["final_response"])

    async def test_ambiguous_target_never_cooperating_gets_clarification(self):
        # B06 shape with the model never cooperating: two simultaneous
        # future scaling rows. The server must not guess one of them —
        # the turn ends on the server-built list clarification, exactly
        # as before, with no confirmation issued.
        await self._add_appointment(
            datetime(2026, 10, 17, 9, 30), self.doctor_a, self.scaling
        )
        await self._add_appointment(
            datetime(2026, 10, 17, 9, 30), self.doctor_b, self.scaling
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {"role": "user", "content": "نوبت جرم‌گیریم رو لغو کن."}
                ]
            ),
            model,
        )
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result.get("pending_action"))
        final = result["final_response"]
        self.assertNotEqual(final, FALLBACK_TEXT)
        self.assertEqual(final.count("دکتر سارا احمدی"), 1)
        self.assertEqual(final.count("دکتر امیر کریمی"), 1)
        self.assertIn("مشخص کنید", final)

    async def test_server_proposal_approves_exactly_once(self):
        # (a) + (c): a stalled turn yields a proposal, the user's approval
        # executes the cancel exactly once, and replaying the same token
        # is rejected without executing again.
        target = await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content="نوبت لغو شد."),
        )
        pending = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت فردام رو لغو کن."}]
            ),
            model,
        )
        self.assertTrue(pending["confirmation_required"])
        token = pending["confirmation_token"]
        self.assertTrue(token)
        rows = list(
            (
                await self.db.execute(
                    select(AgentConfirmation).where(
                        AgentConfirmation.session_id == "sess-regression"
                    )
                )
            )
            .scalars()
            .all()
        )
        self.assertEqual(len(rows), 1)

        result = await self._invoke(
            pending,
            model,
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertTrue(result["last_tool_result"]["ok"])
        self.assertEqual(result["last_tool_result"]["data"]["status"], "cancelled")
        self.assertIsNone(result["pending_action"])
        stored = await self.db.get(Appointment, target.id)
        await self.db.refresh(stored)
        self.assertEqual(stored.status, "cancelled")

        replay = await self._invoke(
            pending,
            model,
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(replay["final_response"], "درخواست انجام نشد.")
        self.assertEqual(model.calls, 5)
        stored = await self.db.get(Appointment, target.id)
        await self.db.refresh(stored)
        self.assertEqual(stored.status, "cancelled")

    async def test_past_target_cancel_is_rejected_explicitly(self):
        # B04 shape with the model never cooperating: the fetch still
        # happens first, then the server rejects the past target
        # explicitly instead of proposing or listing.
        await self._add_appointment(
            datetime(2026, 10, 9, 9, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 10, 9, 10, 0), self.doctor_a, self.filling
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[{"role": "user", "content": "نوبت دیروزم رو لغو کن."}]
            ),
            model,
        )
        self.assertEqual(model.calls, 4)
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result.get("pending_action"))
        self.assertEqual(result["final_response"], PAST_TARGET_MESSAGE)

    async def test_past_destination_reschedule_is_rejected_explicitly(self):
        # B05 shape with the model never cooperating: moving tomorrow's
        # appointment to yesterday is rejected explicitly, and no
        # reschedule is ever proposed.
        await self._add_appointment(
            datetime(2026, 10, 11, 10, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت فردام رو بنداز دیروز ساعت ۹.",
                    }
                ]
            ),
            model,
        )
        self.assertEqual(model.calls, 4)
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result.get("pending_action"))
        self.assertEqual(result["final_response"], PAST_DESTINATION_MESSAGE)

    async def test_past_destination_rejected_even_without_source(self):
        # Live B05-after-B01 interference: B01 already cancelled the
        # shared row, so the source no longer exists — but the destination
        # is still in the past, which is decidable from the user's words
        # alone and must still be rejected explicitly.
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت فردام رو بنداز دیروز ساعت ۹.",
                    }
                ]
            ),
            model,
        )
        self.assertFalse(result["confirmation_required"])
        self.assertEqual(result["final_response"], PAST_DESTINATION_MESSAGE)

    async def test_taken_destination_slot_gets_clarification_not_proposal(self):
        # The destination Saturday 11:00 is already booked for the same
        # doctor: the server must not ask the user to approve a slot the
        # confirmation gate would refuse — it falls back to clarification.
        await self._add_appointment(
            datetime(2026, 10, 17, 10, 0), self.doctor_a, self.filling
        )
        await self._add_appointment(
            datetime(2026, 10, 17, 11, 0), self.doctor_a, self.exam
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=_repeated_list_text()),
            AIMessage(content=_repeated_list_text()),
            AIMessage(content=_repeated_list_text()),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت ترمیمم رو بنداز شنبهٔ آینده ساعت ۱۱.",
                    }
                ]
            ),
            model,
        )
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result.get("pending_action"))
        self.assertIn("مشخص کنید", result["final_response"])

    async def test_unparseable_destination_gets_clarification_not_proposal(self):
        # «یه وقت دیگه» names no date or time: the server cannot build a
        # reschedule proposal and must ask instead of guessing a slot.
        await self._add_appointment(
            datetime(2026, 10, 17, 10, 0), self.doctor_a, self.filling
        )
        model = ScriptedModel(
            _call("get_patient_appointments", {}, "call-list"),
            AIMessage(content=""),
            AIMessage(content=""),
            AIMessage(content=""),
        )
        result = await self._invoke(
            create_initial_state(
                messages=[
                    {
                        "role": "user",
                        "content": "نوبت ترمیمم رو بنداز یه وقت دیگه.",
                    }
                ]
            ),
            model,
        )
        self.assertFalse(result["confirmation_required"])
        self.assertIsNone(result.get("pending_action"))
        self.assertIn("مشخص کنید", result["final_response"])


class RescheduleDestinationParsingTests(unittest.TestCase):
    def test_next_saturday_from_saturday_is_next_week(self):
        self.assertEqual(
            parse_reschedule_destination(
                "شنبهٔ آینده ساعت ۱۱", datetime(2026, 10, 10, 8, 0)
            ),
            ("1405/07/25", "11:00", datetime(2026, 10, 17, 11, 0)),
        )

    def test_bare_weekday_is_the_coming_one(self):
        self.assertEqual(
            parse_reschedule_destination(
                "شنبه ساعت ۱۱", datetime(2026, 10, 13, 8, 0)
            ),
            ("1405/07/25", "11:00", datetime(2026, 10, 17, 11, 0)),
        )

    def test_relative_past_destination(self):
        self.assertEqual(
            parse_reschedule_destination(
                "دیروز ساعت ۹", datetime(2026, 10, 10, 8, 0)
            ),
            ("1405/07/17", "09:00", datetime(2026, 10, 9, 9, 0)),
        )

    def test_time_without_date_is_none(self):
        self.assertIsNone(
            parse_reschedule_destination(
                "ساعت ۱۱", datetime(2026, 10, 10, 8, 0)
            )
        )

    def test_two_dates_are_ambiguous(self):
        self.assertIsNone(
            parse_reschedule_destination(
                "فردا شنبه ساعت ۱۱", datetime(2026, 10, 10, 8, 0)
            )
        )


if __name__ == "__main__":
    unittest.main()
