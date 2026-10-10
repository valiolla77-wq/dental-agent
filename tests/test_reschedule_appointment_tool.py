import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_tools.tools import reschedule_appointment
from app.errors import AppError, ERROR_CATALOG
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.services import appointment_service
from app.utils.date_utils import gregorian_to_jalali


class RescheduleAppointmentToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.target_date = date(2026, 10, 10)  # Saturday
        self.jalali_date = gregorian_to_jalali(
            datetime.combine(self.target_date, time.min)
        )[0]
        self.no_schedule_date = gregorian_to_jalali(
            datetime.combine(self.target_date + timedelta(days=1), time.min)
        )[0]
        async with self.session_factory() as db:
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار نمونه جابه‌جایی",
                phone="09000000000",
            )
            self.doctor = Doctor(
                full_name="پزشک نمونه جابه‌جایی",
                specialty="تخصص نمونه",
                phone="09000000001",
                is_active=True,
            )
            self.service = DentalService(
                name="خدمت نمونه جابه‌جایی", is_active=True
            )
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

    async def _run(self, appointment_id=None, day=None, clock="11:00"):
        async with self.session_factory() as db:
            return await reschedule_appointment(
                db,
                self.appointment.id if appointment_id is None else appointment_id,
                self.jalali_date if day is None else day,
                clock,
            )

    async def _stored_appointment(self):
        async with self.session_factory() as db:
            return await db.get(Appointment, self.appointment.id)

    async def test_reschedule_succeeds_and_returns_minimal_structured_output(self):
        result = await self._run(clock="11:00")

        self.assertTrue(result.ok)
        self.assertEqual(
            set(result.data.model_dump()),
            {
                "appointment_id", "patient_id", "doctor_id", "service_id",
                "appointment_time", "status",
            },
        )
        self.assertEqual(result.data.appointment_id, self.appointment.id)
        self.assertEqual(result.data.patient_id, self.patient.id)
        self.assertEqual(result.data.doctor_id, self.doctor.id)
        self.assertEqual(result.data.service_id, self.service.id)
        self.assertEqual(result.data.appointment_time, f"{self.jalali_date} 11:00")
        self.assertEqual(result.data.status, "scheduled")
        stored = await self._stored_appointment()
        self.assertEqual(stored.appointment_time, datetime(2026, 10, 10, 11))

    async def test_missing_appointment_returns_not_found_code(self):
        result = await self._run(appointment_id=999)
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_NOT_FOUND")

    async def test_cancelled_appointment_cannot_be_rescheduled(self):
        async with self.session_factory() as db:
            appointment = await db.get(Appointment, self.appointment.id)
            appointment.status = "cancelled"
            await db.commit()
        result = await self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_ALREADY_CANCELLED")

    async def test_non_scheduled_status_returns_reschedule_specific_code(self):
        async with self.session_factory() as db:
            appointment = await db.get(Appointment, self.appointment.id)
            appointment.status = "completed"
            await db.commit()
        result = await self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_NOT_RESCHEDULABLE")
        self.assertEqual(
            ERROR_CATALOG[result.error.code].status_code, 409
        )

    async def test_invalid_new_date_returns_catalogued_error(self):
        result = await self._run(day="invalid-date")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_INVALID_DATE_OR_TIME")

    async def test_doctor_without_schedule_on_new_date_is_rejected(self):
        result = await self._run(day=self.no_schedule_date)
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_DOCTOR_NOT_SCHEDULED")

    async def test_already_booked_new_slot_is_rejected(self):
        async with self.session_factory() as db:
            db.add(
                Appointment(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor.id,
                    service_id=self.service.id,
                    appointment_time=datetime(2026, 10, 10, 11),
                    status="scheduled",
                )
            )
            await db.commit()
        result = await self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SLOT_BOOKED")

    async def test_doctor_service_mismatch_is_rejected(self):
        async with self.session_factory() as db:
            await db.execute(
                delete(doctor_dental_services).where(
                    doctor_dental_services.c.doctor_id == self.doctor.id,
                    doctor_dental_services.c.dental_service_id == self.service.id,
                )
            )
            await db.commit()
        result = await self._run()
        self.assertFalse(result.ok)
        self.assertEqual(
            result.error.code, "APPOINTMENT_DOCTOR_SERVICE_MISMATCH"
        )

    async def test_inactive_service_is_rejected(self):
        async with self.session_factory() as db:
            service = await db.get(DentalService, self.service.id)
            service.is_active = False
            await db.commit()
        result = await self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SERVICE_INACTIVE")

    async def test_inactive_doctor_is_rejected(self):
        async with self.session_factory() as db:
            doctor = await db.get(Doctor, self.doctor.id)
            doctor.is_active = False
            await db.commit()
        result = await self._run()
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DOCTOR_INACTIVE")

    async def test_invalid_slot_rolls_back_and_preserves_old_appointment(self):
        result = await self._run(clock="09:15")
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SLOT_INVALID")
        stored = await self._stored_appointment()
        self.assertEqual(stored.appointment_time, datetime(2026, 10, 10, 10))
        self.assertEqual(stored.status, "scheduled")

    async def test_tool_delegates_without_using_database_methods(self):
        fake_db = object()
        appointment = Appointment(
            id=123,
            patient_id=2,
            doctor_id=3,
            service_id=4,
            appointment_time=datetime(2026, 10, 10, 11),
            status="scheduled",
        )
        service_call = AsyncMock(return_value=appointment)
        with patch(
            "app.agent_tools.tools.appointment_service.reschedule_appointment",
            new=service_call,
        ):
            result = await reschedule_appointment(fake_db, 123, self.jalali_date, "11:00")
        service_call.assert_awaited_once_with(
            fake_db, 123, self.jalali_date, "11:00"
        )
        self.assertTrue(result.ok)

    async def test_invalid_tool_input_returns_validation_error_code(self):
        result = await self._run(appointment_id=0)
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_VALIDATION_ERROR")

    async def test_error_results_use_catalog_messages_and_no_exception_details(self):
        result = await self._run(appointment_id=999)
        definition = ERROR_CATALOG[result.error.code]
        self.assertEqual(result.error.message, definition.message)
        self.assertEqual(result.error.details, {})

    async def test_database_failure_rolls_back_old_appointment(self):
        async with self.session_factory() as db:
            with patch(
                "sqlalchemy.ext.asyncio.AsyncSession.flush",
                new=AsyncMock(side_effect=SQLAlchemyError("private failure detail")),
            ):
                result = await reschedule_appointment(
                    db, self.appointment.id, self.jalali_date, "11:00"
                )
        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DATABASE_ERROR")
        stored = await self._stored_appointment()
        self.assertEqual(stored.appointment_time, datetime(2026, 10, 10, 10))


if __name__ == "__main__":
    unittest.main()
