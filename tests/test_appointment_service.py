import unittest
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from pydantic import ValidationError

from app.errors import AppError
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.doctor import Doctor
from app.models.dental_service import DentalService
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.schemas.appointment import AppointmentCreate
from app.services import appointment_service
from app.utils.date_utils import gregorian_to_jalali


class AppointmentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )
        self.target_date = date(2026, 10, 10)  # Saturday
        self.jalali_date = gregorian_to_jalali(
            datetime.combine(self.target_date, time.min)
        )[0]
        async with self.session_factory() as db:
            self.patient = Patient(
                national_id="0000000000",
                full_name="بیمار نمونهٔ ساختگی",
                phone="09000000000",
            )
            self.doctor = Doctor(
                full_name="دکتر نمونهٔ ساختگی",
                specialty="تخصص نمونه",
                phone="09000000001",
                is_active=True,
            )
            self.service = DentalService(
                name="خدمت نمونه",
                description="توضیح نمونه",
                is_active=True,
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
            await db.commit()

    async def _book(self, db, appointment_time, service_id=None, reason=None):
        return await appointment_service.create_appointment(
            db=db,
            patient_id=self.patient.id,
            doctor_id=self.doctor.id,
            service_id=service_id or self.service.id,
            appointment_date=self.jalali_date,
            appointment_time=appointment_time,
            reason=reason,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    def test_service_id_is_required_in_model_and_create_schema(self):
        self.assertFalse(Appointment.__table__.c.service_id.nullable)
        with self.assertRaises(ValidationError):
            AppointmentCreate.model_validate(
                {
                    "patient_id": 1,
                    "doctor_id": 1,
                    "appointment_date": self.jalali_date,
                    "appointment_time": "09:00",
                }
            )

    async def test_create_appointment_at_valid_slot(self):
        async with self.session_factory() as db:
            appointment = await self._book(db, "10:30", reason="نمونه دلیل")

        self.assertIsInstance(appointment, Appointment)
        self.assertEqual(appointment.appointment_time, datetime(2026, 10, 10, 10, 30))
        self.assertEqual(appointment.reason, "نمونه دلیل")
        self.assertEqual(appointment.status, "scheduled")
        self.assertEqual(appointment.service_id, self.service.id)

    async def test_create_outside_schedule_slot_is_rejected(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await self._book(db, "13:00")
        self.assertEqual(raised.exception.code, "APPOINTMENT_SLOT_INVALID")

    async def test_time_inside_schedule_but_between_slots_is_rejected(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await self._book(db, "09:15")
        self.assertEqual(raised.exception.code, "APPOINTMENT_SLOT_INVALID")

    async def test_invalid_jalali_date_is_reported_by_catalog_code(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await appointment_service.create_appointment(
                    db,
                    self.patient.id,
                    self.doctor.id,
                    self.service.id,
                    "invalid-date",
                    "09:00",
                )
        self.assertEqual(raised.exception.code, "APPOINTMENT_INVALID_DATE_OR_TIME")

    async def test_create_for_inactive_doctor_is_rejected(self):
        async with self.session_factory() as db:
            doctor = await db.get(Doctor, self.doctor.id)
            doctor.is_active = False
            await db.commit()
            with self.assertRaises(AppError) as raised:
                await self._book(db, "09:00")
        self.assertEqual(raised.exception.code, "DOCTOR_INACTIVE")

    async def test_missing_patient_is_reported(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await appointment_service.create_appointment(
                    db, 999, self.doctor.id, self.service.id,
                    self.jalali_date, "09:00",
                )
        self.assertEqual(raised.exception.code, "PATIENT_NOT_FOUND")

    async def test_missing_doctor_is_reported(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await appointment_service.create_appointment(
                    db, self.patient.id, 999, self.service.id,
                    self.jalali_date, "09:00",
                )
        self.assertEqual(raised.exception.code, "DOCTOR_NOT_FOUND")

    def test_saturday_based_day_mapping_for_all_weekdays(self):
        saturday = date(2026, 10, 10)
        for offset, expected in enumerate(range(7)):
            with self.subTest(day=expected):
                self.assertEqual(
                    appointment_service.saturday_based_day_of_week(
                        saturday + timedelta(days=offset)
                    ),
                    expected,
                )

    async def test_available_slots_are_generated_at_schedule_intervals(self):
        async with self.session_factory() as db:
            slots = await appointment_service.get_available_slots(
                db, self.doctor.id, self.jalali_date
            )
        self.assertEqual(
            slots,
            ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30"],
        )

    async def test_reserved_scheduled_slot_is_not_available_or_rebookable(self):
        async with self.session_factory() as db:
            await self._book(db, "10:30")
            slots = await appointment_service.get_available_slots(
                db, self.doctor.id, self.jalali_date
            )
            with self.assertRaises(AppError) as raised:
                await self._book(db, "10:30")
        self.assertNotIn("10:30", slots)
        self.assertEqual(raised.exception.code, "APPOINTMENT_SLOT_BOOKED")

    async def test_cancelled_appointment_releases_slot(self):
        async with self.session_factory() as db:
            appointment = await self._book(db, "10:30")
            appointment.status = "cancelled"
            await db.commit()
            slots = await appointment_service.get_available_slots(
                db, self.doctor.id, self.jalali_date
            )
        self.assertIn("10:30", slots)

    async def test_slot_start_is_not_generated_at_schedule_end(self):
        async with self.session_factory() as db:
            slots = await appointment_service.get_available_slots(
                db, self.doctor.id, self.jalali_date
            )
        self.assertNotIn("13:00", slots)
        self.assertTrue(all(slot < "13:00" for slot in slots))

    async def test_patient_appointments_are_returned_in_time_order(self):
        async with self.session_factory() as db:
            later = await self._book(db, "10:00")
            earlier = await self._book(db, "09:00")
            appointments = await appointment_service.get_patient_appointments(
                db, self.patient.id
            )
        self.assertEqual([a.id for a in appointments], [earlier.id, later.id])

    async def test_doctor_service_mismatch_is_rejected(self):
        async with self.session_factory() as db:
            other_service = DentalService(name="خدمت دیگر", is_active=True)
            db.add(other_service)
            await db.commit()
            await db.refresh(other_service)
            with self.assertRaises(AppError) as raised:
                await self._book(db, "09:00", service_id=other_service.id)
        self.assertEqual(
            raised.exception.code,
            "APPOINTMENT_DOCTOR_SERVICE_MISMATCH",
        )

    async def test_inactive_service_cannot_be_booked(self):
        async with self.session_factory() as db:
            service = await db.get(DentalService, self.service.id)
            service.is_active = False
            await db.commit()
            with self.assertRaises(AppError) as raised:
                await self._book(db, "09:00")
        self.assertEqual(raised.exception.code, "APPOINTMENT_SERVICE_INACTIVE")


if __name__ == "__main__":
    unittest.main()
