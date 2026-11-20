"""Direct handler authorization and model-visible output regression tests.

The graph is the normal dispatcher, but ``app.agent_tools.tools`` handlers are
also importable. These tests call them directly to prove that identity and
ownership are enforced inside the handler boundary as well.
"""

import unittest
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_tools.tools import (
    book_appointment,
    cancel_appointment,
    get_patient_appointments,
    reschedule_appointment,
)
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User


class AgentToolAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.db = self.session_factory()

        self.patient_user = User(
            full_name="بیمار متصل",
            phone="09910000001",
            password_hash="unused",
            role="patient",
            is_active=True,
        )
        self.other_user = User(
            full_name="بیمار دیگر",
            phone="09910000002",
            password_hash="unused",
            role="patient",
            is_active=True,
        )
        self.receptionist = User(
            full_name="پذیرش",
            phone="09910000003",
            password_hash="unused",
            role="receptionist",
            is_active=True,
        )
        self.db.add_all(
            [self.patient_user, self.other_user, self.receptionist]
        )
        await self.db.flush()

        self.patient = Patient(
            national_id="2000000001",
            full_name="بیمار متصل",
            phone="09910000001",
            user_id=self.patient_user.id,
        )
        self.other_patient = Patient(
            national_id="2000000002",
            full_name="بیمار دیگر",
            phone="09910000002",
            user_id=self.other_user.id,
        )
        self.doctor = Doctor(
            full_name="دکتر آزمون مجوز",
            specialty="دندانپزشکی عمومی",
            phone="09910000004",
            is_active=True,
        )
        self.service = DentalService(
            name="خدمت آزمون مجوز",
            is_active=True,
        )
        self.doctor.dental_services = [self.service]
        self.db.add_all(
            [self.patient, self.other_patient, self.doctor, self.service]
        )
        await self.db.flush()

        self.own_appointment = Appointment(
            patient_id=self.patient.id,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_time=datetime(2026, 10, 10, 10, 0),
            status="scheduled",
            reason="متن خصوصی",
        )
        self.other_appointment = Appointment(
            patient_id=self.other_patient.id,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_time=datetime(2026, 10, 10, 11, 0),
            status="scheduled",
            reason="متن خصوصی دیگر",
        )
        self.db.add_all([self.own_appointment, self.other_appointment])
        await self.db.commit()
        await self.db.refresh(self.own_appointment)
        await self.db.refresh(self.other_appointment)

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _refresh_appointments(self):
        await self.db.refresh(self.own_appointment)
        await self.db.refresh(self.other_appointment)
        return self.own_appointment, self.other_appointment

    async def test_direct_handlers_reject_missing_actor(self):
        read_result = await get_patient_appointments(
            self.db, self.patient.id, actor=None
        )
        cancel_result = await cancel_appointment(
            self.db, self.own_appointment.id, actor=None
        )
        reschedule_result = await reschedule_appointment(
            self.db,
            self.own_appointment.id,
            "1405/08/15",
            "09:00",
            actor=None,
        )
        book_result = await book_appointment(
            self.db,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_date="1405/08/15",
            appointment_time="09:00",
            patient_id=self.patient.id,
            actor=None,
        )

        for result in (
            read_result,
            cancel_result,
            reschedule_result,
            book_result,
        ):
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "COMMON_FORBIDDEN")

        own, other = await self._refresh_appointments()
        self.assertEqual(own.status, "scheduled")
        self.assertEqual(own.appointment_time, datetime(2026, 10, 10, 10, 0))
        self.assertEqual(other.status, "scheduled")

    async def test_direct_patient_read_rejects_forged_patient_id(self):
        result = await get_patient_appointments(
            self.db, self.other_patient.id, actor=self.patient_user
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_FORBIDDEN")

    async def test_direct_patient_read_returns_own_rows_without_internal_ids(self):
        result = await get_patient_appointments(
            self.db, self.patient.id, actor=self.patient_user
        )

        self.assertTrue(result.ok)
        self.assertEqual(len(result.data), 1)
        row = result.data[0]
        self.assertEqual(
            set(row.model_dump()),
            {
                "doctor_name",
                "service_name",
                "appointment_date",
                "appointment_time",
                "status",
            },
        )
        self.assertEqual(row.doctor_name, self.doctor.full_name)
        self.assertEqual(row.service_name, self.service.name)
        self.assertEqual(row.appointment_time, "10:00")
        self.assertNotIn("appointment_id", row.model_dump())
        self.assertNotIn("patient_id", row.model_dump())
        self.assertNotIn("reason", row.model_dump())

    async def test_direct_patient_booking_rejects_forged_patient_id(self):
        result = await book_appointment(
            self.db,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_date="1405/08/15",
            appointment_time="09:00",
            patient_id=self.other_patient.id,
            actor=self.patient_user,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_FORBIDDEN")
        async with self.session_factory() as db:
            stored = await db.scalar(
                select(Appointment).where(
                    Appointment.patient_id == self.other_patient.id,
                    Appointment.appointment_time == datetime(2026, 10, 10, 9, 0),
                )
            )
        self.assertIsNone(stored)

    async def test_direct_patient_cannot_cancel_another_patients_appointment(self):
        result = await cancel_appointment(
            self.db, self.other_appointment.id, actor=self.patient_user
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_FORBIDDEN")
        own, other = await self._refresh_appointments()
        self.assertEqual(own.status, "scheduled")
        self.assertEqual(other.status, "scheduled")

    async def test_direct_patient_cannot_reschedule_another_patients_appointment(self):
        result = await reschedule_appointment(
            self.db,
            self.other_appointment.id,
            "1405/08/15",
            "09:00",
            actor=self.patient_user,
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_FORBIDDEN")
        own, other = await self._refresh_appointments()
        self.assertEqual(other.appointment_time, datetime(2026, 10, 10, 11, 0))
        self.assertEqual(own.appointment_time, datetime(2026, 10, 10, 10, 0))

    async def test_direct_patient_can_cancel_own_appointment(self):
        result = await cancel_appointment(
            self.db, self.own_appointment.id, actor=self.patient_user
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.data.status, "cancelled")
        self.assertNotIn("appointment_id", result.model_dump())
        own, other = await self._refresh_appointments()
        self.assertEqual(own.status, "cancelled")
        self.assertEqual(other.status, "scheduled")


if __name__ == "__main__":
    unittest.main()
