"""End-to-end Agent chat -> booking tests over HTTP.

A fake tool-calling model drives the real LangGraph graph, agent tools,
persisted confirmation flow, booking service, and a temporary in-memory
database. No external LLM, SMS, or real database is used.

Confirmation replay, foreign-user/session, rejection, expiry, and generic
tool-failure mechanics are already covered in ``test_agent_chat.py``; this
module adds the missing free-slot -> booking proposal -> approval path.
"""

import json
import os
import unittest
from datetime import datetime, time

# Set test environment variables BEFORE importing app modules.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CONFIRMATION_HMAC_SECRET"] = (
    "test-confirmation-hmac-secret-32-chars-long"
)
os.environ["CONFIRMATION_TTL_SECONDS"] = "300"

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.agent_confirmation import AgentConfirmation  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_schedule import DoctorSchedule  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.routers.agent_chat import get_chat_llm  # noqa: E402
from app.utils.date_utils import gregorian_to_jalali  # noqa: E402


def _tool_call(name, arguments, call_id):
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": name,
                "args": arguments,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


class ToolAwareFakeModel:
    """Scripted model that phrases the final reply from the real tool result."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.received = []
        self.tool_schemas = []

    def bind_tools(self, tool_schemas):
        self.tool_schemas = list(tool_schemas)
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        self.received.append(list(messages))
        if self.responses:
            return self.responses.pop(0)

        last = messages[-1]
        if not isinstance(last, ToolMessage):
            raise AssertionError("dynamic reply expected a ToolMessage")
        payload = json.loads(last.content)
        if payload.get("ok"):
            data = payload["data"]
            return AIMessage(
                content=(
                    f"نوبت {data['appointment_id']} برای "
                    f"{data['appointment_time']} ثبت شد."
                )
            )
        error = payload.get("error") or {}
        return AIMessage(
            content=f"رزرو انجام نشد: {error.get('code', 'UNKNOWN')}"
        )


class FailingFinalModel(ToolAwareFakeModel):
    """Completes the proposal, then fails when asked to phrase the result."""

    async def ainvoke(self, messages):
        self.calls += 1
        self.received.append(list(messages))
        if self.responses:
            return self.responses.pop(0)
        raise RuntimeError("simulated final LLM failure")


class AgentChatBookingEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.factory()
        self.client = TestClient(app)

        async def _override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = _override_get_db
        self.jalali_date = gregorian_to_jalali(
            datetime(2026, 10, 10, 0, 0)
        )[0]

        service = DentalService(name="خدمت تست چت رزرو", is_active=True)
        self.session.add(service)
        await self.session.flush()
        doctor = Doctor(
            full_name="دکتر تست چت رزرو",
            specialty="تخصص تست",
            phone="09360005001",
            is_active=True,
            dental_services=[service],
        )
        self.session.add(doctor)
        await self.session.flush()
        self.session.add(
            DoctorSchedule(
                doctor_id=doctor.id,
                day_of_week=0,
                start_time=time(9),
                end_time=time(13),
                slot_duration_minutes=30,
                is_active=True,
            )
        )
        user = User(
            full_name="بیمار تست چت رزرو",
            phone="09360005002",
            password_hash=hash_password("patient-pass-123"),
            role="patient",
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        patient = Patient(
            national_id="9500000001",
            full_name="بیمار تست چت رزرو",
            phone="09360005002",
            user_id=user.id,
        )
        self.session.add(patient)
        await self.session.commit()

        self.service_id = service.id
        self.doctor_id = doctor.id
        self.patient_id = patient.id
        self.user_id = user.id
        self.token = create_access_token(subject=str(user.id))

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_chat_llm, None)
        await self.session.close()
        await self.engine.dispose()

    def _install_llm(self, model):
        app.dependency_overrides[get_chat_llm] = lambda: model

    def _post(self, *, message, session_id, confirmation=None):
        body = {"message": message, "session_id": session_id}
        if confirmation is not None:
            body["confirmation"] = confirmation
        return self.client.post(
            "/agent/chat",
            json=body,
            headers={"Authorization": f"Bearer {self.token}"},
        )

    def _booking_model(self):
        return ToolAwareFakeModel(
            _tool_call(
                "find_available_slots",
                {
                    "service_id": self.service_id,
                    "doctor_id": self.doctor_id,
                    "appointment_date": self.jalali_date,
                },
                "call-find-1",
            ),
            _tool_call(
                "book_appointment",
                {
                    "doctor_id": self.doctor_id,
                    "service_id": self.service_id,
                    "appointment_date": self.jalali_date,
                    "appointment_time": "09:00",
                    "patient_id": self.patient_id,
                },
                "call-book-1",
            ),
        )

    async def _appointments_at_slot(self, clock="09:00"):
        result = await self.session.execute(
            select(Appointment).where(
                Appointment.doctor_id == self.doctor_id,
                Appointment.appointment_time
                == datetime(2026, 10, 10, int(clock[:2]), int(clock[3:])),
            )
        )
        return list(result.scalars().all())

    def _propose_booking(self, model, session_id):
        self._install_llm(model)
        return self._post(
            message="برای همین شنبه ساعت ۹ نوبت رزرو کن",
            session_id=session_id,
        )

    async def test_chat_finds_slot_proposes_and_books_after_approval(self):
        model = self._booking_model()
        proposed = self._propose_booking(model, "booking-e2e")

        self.assertEqual(proposed.status_code, 200, proposed.text)
        payload = proposed.json()
        self.assertTrue(payload["confirmation_required"])
        self.assertTrue(payload["confirmation_token"])
        self.assertEqual(payload["session_id"], "booking-e2e")
        self.assertIn(str(self.doctor_id), payload["confirmation_prompt"])
        self.assertIn("09:00", payload["confirmation_prompt"])

        # The read tool really found the free slot before the proposal.
        tool_message = model.received[1][-1]
        self.assertIsInstance(tool_message, ToolMessage)
        slots_payload = json.loads(tool_message.content)
        self.assertTrue(slots_payload["ok"])
        self.assertIn("09:00", slots_payload["data"]["available_slots"])

        # Nothing is booked before approval.
        self.assertEqual(await self._appointments_at_slot(), [])

        approved = self._post(
            message="تأیید می‌کنم",
            session_id="booking-e2e",
            confirmation={
                "token": payload["confirmation_token"],
                "decision": "approved",
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        final = approved.json()
        self.assertFalse(final["confirmation_required"])
        self.assertIsNone(final["confirmation_token"])

        appointments = await self._appointments_at_slot()
        self.assertEqual(len(appointments), 1)
        appointment = appointments[0]
        self.assertEqual(appointment.patient_id, self.patient_id)
        self.assertEqual(appointment.doctor_id, self.doctor_id)
        self.assertEqual(appointment.service_id, self.service_id)
        self.assertEqual(appointment.status, "scheduled")
        self.assertEqual(
            final["reply"],
            f"نوبت {appointment.id} برای {self.jalali_date} 09:00 ثبت شد.",
        )
        self.assertEqual(model.calls, 3)

        final_messages = model.received[-1]
        assistant_index = next(
            index
            for index, message in enumerate(final_messages)
            if isinstance(message, AIMessage) and message.tool_calls
        )
        tool_index = next(
            index
            for index, message in enumerate(final_messages)
            if isinstance(message, ToolMessage)
        )
        self.assertLess(assistant_index, tool_index)
        tool_call = final_messages[assistant_index].tool_calls[0]
        self.assertEqual(tool_call["name"], "book_appointment")
        self.assertEqual(
            tool_call["id"], final_messages[tool_index].tool_call_id
        )
        self.assertEqual(tool_call["args"]["doctor_id"], self.doctor_id)
        self.assertEqual(tool_call["args"]["service_id"], self.service_id)

    async def test_slot_occupied_before_approval_prevents_booking(self):
        model = self._booking_model()
        proposed = self._propose_booking(model, "booking-race")
        self.assertEqual(proposed.status_code, 200, proposed.text)
        token = proposed.json()["confirmation_token"]

        # Another booking occupies the slot after the proposal.
        self.session.add(
            Appointment(
                patient_id=self.patient_id,
                doctor_id=self.doctor_id,
                service_id=self.service_id,
                appointment_time=datetime(2026, 10, 10, 9, 0),
                status="scheduled",
            )
        )
        await self.session.commit()

        approved = self._post(
            message="تأیید می‌کنم",
            session_id="booking-race",
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        final = approved.json()
        self.assertFalse(final["confirmation_required"])
        self.assertIn("APPOINTMENT_SLOT_BOOKED", final["reply"])

        appointments = await self._appointments_at_slot()
        self.assertEqual(len(appointments), 1)

        result = await self.session.execute(
            select(AgentConfirmation).where(
                AgentConfirmation.user_id == self.user_id
            )
        )
        confirmation = result.scalar_one()
        self.assertIsNotNone(confirmation.consumed_at)
        self.assertEqual(confirmation.decision, "approved")

    async def test_tool_failure_does_not_report_false_success(self):
        model = self._booking_model()
        proposed = self._propose_booking(model, "booking-tool-fail")
        self.assertEqual(proposed.status_code, 200, proposed.text)
        token = proposed.json()["confirmation_token"]

        service = await self.session.get(DentalService, self.service_id)
        service.is_active = False
        await self.session.commit()

        approved = self._post(
            message="تأیید می‌کنم",
            session_id="booking-tool-fail",
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        final = approved.json()
        self.assertFalse(final["confirmation_required"])
        self.assertIn("APPOINTMENT_SERVICE_INACTIVE", final["reply"])
        self.assertNotIn("ثبت شد", final["reply"])
        self.assertEqual(await self._appointments_at_slot(), [])

    async def test_final_llm_failure_after_booking_returns_safe_success(self):
        model = FailingFinalModel(
            *self._booking_model().responses
        )
        proposed = self._propose_booking(model, "booking-llm-fail")
        self.assertEqual(proposed.status_code, 200, proposed.text)
        token = proposed.json()["confirmation_token"]
        self.assertEqual(await self._appointments_at_slot(), [])

        approved = self._post(
            message="تأیید می‌کنم",
            session_id="booking-llm-fail",
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        final = approved.json()
        self.assertFalse(final["confirmation_required"])

        appointments = await self._appointments_at_slot()
        self.assertEqual(len(appointments), 1)
        appointment = appointments[0]
        self.assertIn(f"نوبت {appointment.id}", final["reply"])
        self.assertIn("ثبت شد", final["reply"])
        self.assertNotIn("خطای داخلی", final["reply"])
        self.assertEqual(model.calls, 3)

    async def test_llm_failure_after_tool_failure_claims_no_success(self):
        model = FailingFinalModel(
            *self._booking_model().responses
        )
        proposed = self._propose_booking(model, "booking-tool-llm-fail")
        self.assertEqual(proposed.status_code, 200, proposed.text)
        token = proposed.json()["confirmation_token"]

        service = await self.session.get(DentalService, self.service_id)
        service.is_active = False
        await self.session.commit()

        approved = self._post(
            message="تأیید می‌کنم",
            session_id="booking-tool-llm-fail",
            confirmation={"token": token, "decision": "approved"},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        final = approved.json()
        self.assertNotIn("ثبت شد", final["reply"])
        self.assertNotIn("لغو شد", final["reply"])
        self.assertEqual(await self._appointments_at_slot(), [])


if __name__ == "__main__":
    unittest.main()
