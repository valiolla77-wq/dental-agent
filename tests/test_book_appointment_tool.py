import unittest
from datetime import date, datetime, time
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_tools.tools import book_appointment
from app.errors import AppError
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.services import appointment_service
from app.utils.date_utils import gregorian_to_jalali


class BookAppointmentToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        target = datetime.combine(date(2026, 10, 10), time.min)
        self.appointment_date = gregorian_to_jalali(target)[0]
        async with self.session_factory() as db:
            self.service = DentalService(name="جرم‌گیری نمونه", is_active=True)
            self.other_service = DentalService(name="ترمیم نمونه", is_active=True)
            self.inactive_service = DentalService(
                name="خدمت غیرفعال نمونه",
                is_active=False,
            )
            db.add_all([self.service, self.other_service, self.inactive_service])
            await db.flush()
            self.doctor = Doctor(
                full_name="دکتر فعال نمونه",
                specialty="تخصص نمونه",
                phone="09000000001",
                is_active=True,
                dental_services=[self.service],
            )
            self.inactive_doctor = Doctor(
                full_name="دکتر غیرفعال نمونه",
                specialty="تخصص نمونه",
                phone="09000000002",
                is_active=False,
                dental_services=[self.service],
            )
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار موجود نمونه",
                phone="09000000003",
            )
            db.add_all([self.doctor, self.inactive_doctor, self.patient])
            await db.flush()
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
            await db.commit()
            for item in (
                self.service,
                self.other_service,
                self.inactive_service,
                self.doctor,
                self.inactive_doctor,
                self.patient,
            ):
                await db.refresh(item)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _book(self, db, **overrides):
        args = {
            "doctor_id": self.doctor.id,
            "service_id": self.service.id,
            "appointment_date": self.appointment_date,
            "appointment_time": "10:30",
            "patient_id": self.patient.id,
        }
        args.update(overrides)
        return await book_appointment(db, **args)

    async def test_successful_booking_with_existing_patient_is_minimal(self):
        async with self.session_factory() as db:
            result = await self._book(db, reason="توضیح خصوصی نباید برگردد")

        self.assertTrue(result.ok)
        self.assertEqual(result.data.patient_id, self.patient.id)
        self.assertEqual(result.data.doctor_id, self.doctor.id)
        self.assertEqual(result.data.service_id, self.service.id)
        self.assertEqual(result.data.appointment_time, f"{self.appointment_date} 10:30")
        self.assertEqual(result.data.status, "scheduled")
        self.assertGreater(result.data.appointment_id, 0)
        self.assertEqual(
            set(result.data.model_dump()),
            {
                "appointment_id",
                "patient_id",
                "doctor_id",
                "service_id",
                "appointment_time",
                "status",
            },
        )
        self.assertNotIn("reason", result.data.model_dump())
        self.assertNotIn(self.patient.national_id, result.model_dump_json())

    async def test_existing_patient_is_found_by_national_id(self):
        async with self.session_factory() as db:
            result = await self._book(
                db,
                patient_id=None,
                national_id=self.patient.national_id,
                full_name="نام ورودی نادیده",
                phone="09000000999",
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.data.patient_id, self.patient.id)

    async def test_new_patient_is_created_by_booking_service(self):
        async with self.session_factory() as db:
            result = await self._book(
                db,
                patient_id=None,
                national_id="0000000001",
                full_name="بیمار جدید نمونه",
                phone="09000000004",
            )

        self.assertTrue(result.ok)
        async with self.session_factory() as db:
            patient = await db.scalar(
                select(Patient).where(Patient.national_id == "0000000001")
            )
        self.assertEqual(result.data.patient_id, patient.id)

    async def test_already_booked_slot_returns_catalog_error(self):
        async with self.session_factory() as db:
            await appointment_service.create_appointment(
                db,
                self.patient.id,
                self.doctor.id,
                self.service.id,
                self.appointment_date,
                "10:30",
            )
        async with self.session_factory() as db:
            result = await self._book(db)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SLOT_BOOKED")

    async def test_inactive_doctor_returns_catalog_error(self):
        async with self.session_factory() as db:
            result = await self._book(db, doctor_id=self.inactive_doctor.id)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DOCTOR_INACTIVE")

    async def test_doctor_service_mismatch_returns_catalog_error(self):
        async with self.session_factory() as db:
            result = await self._book(db, service_id=self.other_service.id)

        self.assertFalse(result.ok)
        self.assertEqual(
            result.error.code,
            "APPOINTMENT_DOCTOR_SERVICE_MISMATCH",
        )

    async def test_inactive_service_returns_catalog_error(self):
        async with self.session_factory() as db:
            result = await self._book(db, service_id=self.inactive_service.id)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SERVICE_INACTIVE")

    async def test_unknown_service_returns_catalog_error(self):
        async with self.session_factory() as db:
            result = await self._book(db, service_id=999)

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DENTAL_SERVICE_NOT_FOUND")

    async def test_failed_booking_rolls_back_new_patient(self):
        async with self.session_factory() as db:
            result = await self._book(
                db,
                appointment_time="09:15",
                patient_id=None,
                national_id="0000000002",
                full_name="بیمار Rollback نمونه",
                phone="09000000005",
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "APPOINTMENT_SLOT_INVALID")
        async with self.session_factory() as db:
            patient = await db.scalar(
                select(Patient).where(Patient.national_id == "0000000002")
            )
            appointment_count = await db.scalar(
                select(Appointment.id).where(Appointment.patient_id == patient.id)
            ) if patient is not None else None
        self.assertIsNone(patient)
        self.assertIsNone(appointment_count)

    async def test_invalid_input_returns_validation_error(self):
        async with self.session_factory() as db:
            result = await self._book(
                db,
                patient_id=None,
                national_id=None,
                full_name=None,
                phone=None,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "COMMON_VALIDATION_ERROR")

    async def test_database_error_is_generic_and_does_not_log_patient_data(self):
        private_value = "9876543210"
        async with self.session_factory() as db:
            with patch(
                "app.agent_tools.tools.booking_service.create_booking",
                new=AsyncMock(side_effect=SQLAlchemyError(private_value)),
            ):
                with self.assertLogs("dental_agent.agent_tools", level="ERROR") as logs:
                    result = await self._book(
                        db,
                        patient_id=None,
                        national_id=private_value,
                        full_name="نام محرمانه",
                        phone="09000000009",
                    )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "DATABASE_ERROR")
        self.assertNotIn(private_value, result.model_dump_json())
        log_output = "\n".join(logs.output)
        self.assertNotIn(private_value, log_output)
        self.assertNotIn("نام محرمانه", log_output)
        self.assertNotIn("09000000009", log_output)

    async def test_unexpected_error_is_generic_and_does_not_log_patient_data(self):
        private_value = "9876543211"
        async with self.session_factory() as db:
            with patch(
                "app.agent_tools.tools.booking_service.create_booking",
                new=AsyncMock(side_effect=RuntimeError(private_value)),
            ):
                with self.assertLogs("dental_agent.agent_tools", level="ERROR") as logs:
                    result = await self._book(
                        db,
                        patient_id=None,
                        national_id=private_value,
                        full_name="نام محرمانه",
                        phone="09000000010",
                    )

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code, "INTERNAL_ERROR")
        self.assertNotIn(private_value, result.model_dump_json())
        log_output = "\n".join(logs.output)
        self.assertNotIn(private_value, log_output)
        self.assertNotIn("نام محرمانه", log_output)
        self.assertNotIn("09000000010", log_output)


if __name__ == "__main__":
    unittest.main()
