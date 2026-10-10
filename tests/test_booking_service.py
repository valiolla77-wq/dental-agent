import unittest
from datetime import date, datetime, time

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.schemas.appointment import AppointmentCreate
from app.services import (
    appointment_service,
    booking_service,
    dental_service_service,
)
from app.utils.date_utils import gregorian_to_jalali


class BookingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        target_date = datetime.combine(date(2026, 10, 10), time.min)
        self.appointment_date = gregorian_to_jalali(target_date)[0]

        async with self.session_factory() as db:
            self.service = DentalService(name="جرم‌گیری نمونه", is_active=True)
            self.inactive_service = DentalService(
                name="خدمت غیرفعال نمونه",
                is_active=False,
            )
            db.add_all([self.service, self.inactive_service])
            await db.flush()
            self.doctor = Doctor(
                full_name="دکتر نمونهٔ رزرو",
                specialty="تخصص نمونه",
                phone="09000000001",
                is_active=True,
                dental_services=[self.service],
            )
            db.add(self.doctor)
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
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار موجود نمونه",
                phone="09000000002",
            )
            db.add(self.patient)
            await db.commit()
            await db.refresh(self.patient)
            await db.refresh(self.doctor)
            await db.refresh(self.service)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _book_new_patient(self, db, appointment_time="10:30", **kwargs):
        return await booking_service.create_booking(
            db,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_date=self.appointment_date,
            appointment_time=appointment_time,
            national_id="0000000001",
            full_name="بیمار جدید نمونه",
            phone="09000000003",
            **kwargs,
        )

    async def test_complete_booking_flow_creates_patient_and_appointment(self):
        async with self.session_factory() as db:
            services = await dental_service_service.list_dental_services(db)
            doctors = await dental_service_service.get_service_doctors(
                db,
                self.service.id,
            )
            slots = await appointment_service.get_available_slots(
                db,
                self.doctor.id,
                self.appointment_date,
            )
            await db.commit()
            appointment = await self._book_new_patient(db)

        self.assertEqual([service.id for service in services], [self.service.id])
        self.assertEqual([doctor.id for doctor in doctors], [self.doctor.id])
        self.assertIn("10:30", slots)
        self.assertEqual(appointment.service_id, self.service.id)
        self.assertEqual(appointment.appointment_time, datetime(2026, 10, 10, 10, 30))
        async with self.session_factory() as db:
            created_patient = await db.scalar(
                select(Patient).where(Patient.national_id == "0000000001")
            )
        self.assertIsNotNone(created_patient)
        self.assertEqual(appointment.patient_id, created_patient.id)

    async def test_existing_patient_is_reused_by_national_id(self):
        async with self.session_factory() as db:
            appointment = await booking_service.create_booking(
                db,
                doctor_id=self.doctor.id,
                service_id=self.service.id,
                appointment_date=self.appointment_date,
                appointment_time="09:00",
                national_id=self.patient.national_id,
                full_name="ورودی نادیده برای بیمار موجود",
                phone="09000000099",
            )
            patient_count = await db.scalar(select(func.count(Patient.id)))

        self.assertEqual(appointment.patient_id, self.patient.id)
        self.assertEqual(patient_count, 1)

    async def test_failed_booking_rolls_back_new_patient(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await self._book_new_patient(db, appointment_time="13:00")
        self.assertEqual(raised.exception.code, "APPOINTMENT_SLOT_INVALID")
        async with self.session_factory() as db:
            patient = await db.scalar(
                select(Patient).where(Patient.national_id == "0000000001")
            )
        self.assertIsNone(patient)

    async def test_repeated_booking_returns_slot_booked_error(self):
        async with self.session_factory() as db:
            await self._book_new_patient(db)
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await self._book_new_patient(db)
        self.assertEqual(raised.exception.code, "APPOINTMENT_SLOT_BOOKED")

    async def test_doctor_and_service_business_errors_are_preserved(self):
        async with self.session_factory() as db:
            cases = (
                (999, self.service.id, "DOCTOR_NOT_FOUND"),
                (
                    self.doctor.id,
                    999,
                    "DENTAL_SERVICE_NOT_FOUND",
                ),
                (
                    self.doctor.id,
                    self.inactive_service.id,
                    "APPOINTMENT_SERVICE_INACTIVE",
                ),
            )
            for doctor_id, service_id, expected_code in cases:
                with self.subTest(code=expected_code):
                    with self.assertRaises(AppError) as raised:
                        await booking_service.create_booking(
                            db,
                            doctor_id=doctor_id,
                            service_id=service_id,
                            appointment_date=self.appointment_date,
                            appointment_time="09:00",
                            national_id="0000000005",
                            full_name="بیمار نمونه",
                            phone="09000000005",
                        )
                    self.assertEqual(raised.exception.code, expected_code)
                    await db.rollback()

    async def test_missing_schedule_is_reported_and_no_slots_are_returned(self):
        async with self.session_factory() as db:
            new_doctor = Doctor(
                full_name="دکتر بدون برنامه نمونه",
                specialty="تخصص نمونه",
                phone="09000000006",
                is_active=True,
                dental_services=[self.service],
            )
            db.add(new_doctor)
            await db.commit()
            await db.refresh(new_doctor)
            slots = await appointment_service.get_available_slots(
                db,
                new_doctor.id,
                self.appointment_date,
            )
            await db.commit()
            with self.assertRaises(AppError) as raised:
                await booking_service.create_booking(
                    db,
                    doctor_id=new_doctor.id,
                    service_id=self.service.id,
                    appointment_date=self.appointment_date,
                    appointment_time="09:00",
                    patient_id=self.patient.id,
                )
        self.assertEqual(slots, [])
        self.assertEqual(
            raised.exception.code,
            "APPOINTMENT_DOCTOR_NOT_SCHEDULED",
        )

    async def test_appointment_request_accepts_legacy_or_new_patient(self):
        legacy = AppointmentCreate(
            patient_id=self.patient.id,
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_date=self.appointment_date,
            appointment_time="09:00",
        )
        new_patient = AppointmentCreate(
            national_id="0000000004",
            full_name="بیمار ورودی نمونه",
            phone="09000000004",
            doctor_id=self.doctor.id,
            service_id=self.service.id,
            appointment_date=self.appointment_date,
            appointment_time="09:30",
        )
        self.assertEqual(legacy.patient_id, self.patient.id)
        self.assertEqual(new_patient.national_id, "0000000004")

    async def test_appointment_request_rejects_incomplete_or_ambiguous_patient(self):
        common = {
            "doctor_id": self.doctor.id,
            "service_id": self.service.id,
            "appointment_date": self.appointment_date,
            "appointment_time": "09:00",
        }
        for patient_data in (
            {},
            {"patient_id": self.patient.id, "national_id": "0000000001"},
            {"national_id": "0000000001", "full_name": "نام نمونه"},
        ):
            with self.subTest(patient_data=patient_data):
                with self.assertRaises(ValidationError):
                    AppointmentCreate(**common, **patient_data)


if __name__ == "__main__":
    unittest.main()
