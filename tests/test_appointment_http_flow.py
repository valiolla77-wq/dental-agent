"""HTTP integration tests for booking and rescheduling transaction boundaries.

These tests exercise the real routers, authorization checks, services, and
database session dependency. They use the process-wide in-memory test database
and a unique doctor/service fixture; the real SQLite database is never touched.
"""

import asyncio
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

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_dental_service import doctor_dental_services  # noqa: E402
from app.models.doctor_schedule import DoctorSchedule  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.date_utils import gregorian_to_jalali  # noqa: E402

DOCTOR_PHONE = "09360003001"
PATIENT_PHONE = "09360003002"
OTHER_PATIENT_PHONE = "09360003003"
RECEPTIONIST_PHONE = "09360003004"
PATIENT_NATIONAL_ID = "9300000001"
OTHER_NATIONAL_ID = "9300000002"
DOCTOR_NAME = "دکتر تست تراکنش رزرو"
SERVICE_NAME = "خدمت تست تراکنش رزرو"


def _run(coro):
    return asyncio.run(coro)


def _seed_fixture():
    async def _seed():
        async with SessionLocal() as db:
            service = DentalService(name=SERVICE_NAME, is_active=True)
            db.add(service)
            await db.flush()

            doctor = Doctor(
                full_name=DOCTOR_NAME,
                specialty="تخصص تست",
                phone=DOCTOR_PHONE,
                is_active=True,
                dental_services=[service],
            )
            db.add(doctor)
            await db.flush()

            patient_user = User(
                full_name="بیمار تست تراکنش",
                phone=PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            other_user = User(
                full_name="بیمار دیگر تست تراکنش",
                phone=OTHER_PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            receptionist = User(
                full_name="پذیرش تست تراکنش",
                phone=RECEPTIONIST_PHONE,
                password_hash=hash_password("reception-pass-123"),
                role="receptionist",
                is_active=True,
            )
            db.add_all([patient_user, other_user, receptionist])
            await db.flush()

            own_patient = Patient(
                national_id=PATIENT_NATIONAL_ID,
                full_name="بیمار تست تراکنش",
                phone=PATIENT_PHONE,
                user_id=patient_user.id,
            )
            other_patient = Patient(
                national_id=OTHER_NATIONAL_ID,
                full_name="بیمار دیگر تست تراکنش",
                phone=OTHER_PATIENT_PHONE,
                user_id=other_user.id,
            )
            db.add_all([own_patient, other_patient])
            db.add(
                DoctorSchedule(
                    doctor_id=doctor.id,
                    day_of_week=0,
                    start_time=time(9),
                    end_time=time(13),
                    slot_duration_minutes=30,
                    is_active=True,
                )
            )
            await db.flush()
            await db.commit()
            return {
                "doctor_id": doctor.id,
                "service_id": service.id,
                "patient_id": own_patient.id,
                "other_patient_id": other_patient.id,
                "patient_user_id": patient_user.id,
                "other_user_id": other_user.id,
                "receptionist_id": receptionist.id,
            }

    return _run(_seed())


def _add_appointment(patient_id, doctor_id, service_id, clock="09:00"):
    async def _add():
        async with SessionLocal() as db:
            appointment = Appointment(
                patient_id=patient_id,
                doctor_id=doctor_id,
                service_id=service_id,
                appointment_time=datetime(2026, 10, 10, int(clock[:2]), int(clock[3:])),
                status="scheduled",
            )
            db.add(appointment)
            await db.commit()
            await db.refresh(appointment)
            return appointment.id

    return _run(_add())


def _get_appointment(appointment_id):
    async def _get():
        async with SessionLocal() as db:
            appointment = await db.get(Appointment, appointment_id)
            if appointment is None:
                return None
            return {
                "id": appointment.id,
                "patient_id": appointment.patient_id,
                "appointment_time": appointment.appointment_time,
                "status": appointment.status,
            }

    return _run(_get())


def _count_appointments(doctor_id, clock):
    async def _count():
        async with SessionLocal() as db:
            return await db.scalar(
                select(func.count(Appointment.id)).where(
                    Appointment.doctor_id == doctor_id,
                    Appointment.appointment_time
                    == datetime(2026, 10, 10, int(clock[:2]), int(clock[3:])),
                )
            )

    return _run(_count())


def _count_patients(national_id):
    async def _count():
        async with SessionLocal() as db:
            return await db.scalar(
                select(func.count(Patient.id)).where(
                    Patient.national_id == national_id
                )
            )

    return _run(_count())


def _cleanup_fixture(fixture):
    async def _cleanup():
        async with SessionLocal() as db:
            await db.execute(
                delete(Appointment).where(
                    Appointment.doctor_id == fixture["doctor_id"]
                )
            )
            await db.execute(
                delete(DoctorSchedule).where(
                    DoctorSchedule.doctor_id == fixture["doctor_id"]
                )
            )
            await db.execute(
                delete(doctor_dental_services).where(
                    doctor_dental_services.c.doctor_id
                    == fixture["doctor_id"]
                )
            )
            await db.execute(
                delete(Patient).where(
                    Patient.id.in_(
                        [
                            fixture["patient_id"],
                            fixture["other_patient_id"],
                        ]
                    )
                )
            )
            await db.execute(
                delete(User).where(
                    User.id.in_(
                        [
                            fixture["patient_user_id"],
                            fixture["other_user_id"],
                            fixture["receptionist_id"],
                        ]
                    )
                )
            )
            await db.execute(
                delete(Doctor).where(Doctor.id == fixture["doctor_id"])
            )
            await db.execute(
                delete(DentalService).where(
                    DentalService.id == fixture["service_id"]
                )
            )
            await db.commit()

    _run(_cleanup())


class AppointmentHttpTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.fixture = _seed_fixture()
        self.client = TestClient(app)
        self.jalali_date = gregorian_to_jalali(
            datetime(2026, 10, 10, 0, 0)
        )[0]
        self.patient_token = create_access_token(
            subject=str(self.fixture["patient_user_id"])
        )
        self.other_token = create_access_token(
            subject=str(self.fixture["other_user_id"])
        )
        self.receptionist_token = create_access_token(
            subject=str(self.fixture["receptionist_id"])
        )

    def tearDown(self):
        _cleanup_fixture(self.fixture)

    def _headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _book(self, token, **overrides):
        body = {
            "doctor_id": self.fixture["doctor_id"],
            "service_id": self.fixture["service_id"],
            "appointment_date": self.jalali_date,
            "appointment_time": "09:00",
        }
        body.update(overrides)
        return self.client.post(
            "/appointments/",
            json=body,
            headers=self._headers(token),
        )

    def _reschedule(self, token, appointment_id, clock):
        return self.client.post(
            f"/appointments/{appointment_id}/reschedule",
            json={
                "appointment_date": self.jalali_date,
                "appointment_time": clock,
            },
            headers=self._headers(token),
        )

    def test_patient_can_book_for_own_linked_record(self):
        response = self._book(
            self.patient_token,
            patient_id=self.fixture["patient_id"],
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["patient_id"], self.fixture["patient_id"])
        self.assertEqual(payload["status"], "scheduled")
        stored = _get_appointment(payload["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored["status"], "scheduled")

    def test_patient_can_book_with_own_national_id(self):
        response = self._book(
            self.patient_token,
            national_id=PATIENT_NATIONAL_ID,
            full_name="بیمار تست تراکنش",
            phone=PATIENT_PHONE,
            appointment_time="09:30",
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["patient_id"], self.fixture["patient_id"]
        )

    def test_receptionist_can_book_with_patient_id(self):
        response = self._book(
            self.receptionist_token,
            patient_id=self.fixture["other_patient_id"],
            appointment_time="10:00",
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["patient_id"], self.fixture["other_patient_id"]
        )

    def test_patient_can_reschedule_own_appointment(self):
        appointment_id = _add_appointment(
            self.fixture["patient_id"],
            self.fixture["doctor_id"],
            self.fixture["service_id"],
            clock="09:00",
        )
        response = self._reschedule(
            self.patient_token, appointment_id, "11:00"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["appointment_time"], "11:00")
        stored = _get_appointment(appointment_id)
        self.assertEqual(stored["appointment_time"], datetime(2026, 10, 10, 11, 0))

    def test_patient_cannot_reschedule_another_patients_appointment(self):
        appointment_id = _add_appointment(
            self.fixture["other_patient_id"],
            self.fixture["doctor_id"],
            self.fixture["service_id"],
            clock="09:00",
        )
        response = self._reschedule(
            self.patient_token, appointment_id, "11:00"
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "COMMON_FORBIDDEN")
        stored = _get_appointment(appointment_id)
        self.assertEqual(
            stored["appointment_time"], datetime(2026, 10, 10, 9, 0)
        )

    def test_failed_booking_leaves_no_partial_appointment(self):
        # Occupy the requested slot first.
        _add_appointment(
            self.fixture["other_patient_id"],
            self.fixture["doctor_id"],
            self.fixture["service_id"],
            clock="10:30",
        )
        before = _count_appointments(self.fixture["doctor_id"], "10:30")
        patient_count_before = _count_patients(OTHER_NATIONAL_ID)

        response = self._book(
            self.patient_token,
            patient_id=self.fixture["patient_id"],
            appointment_time="10:30",
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["error"]["code"], "APPOINTMENT_SLOT_BOOKED"
        )
        self.assertEqual(
            _count_appointments(self.fixture["doctor_id"], "10:30"), before
        )
        self.assertEqual(
            _count_patients(OTHER_NATIONAL_ID), patient_count_before
        )

    def test_failed_reschedule_keeps_original_time(self):
        appointment_id = _add_appointment(
            self.fixture["patient_id"],
            self.fixture["doctor_id"],
            self.fixture["service_id"],
            clock="09:00",
        )
        _add_appointment(
            self.fixture["other_patient_id"],
            self.fixture["doctor_id"],
            self.fixture["service_id"],
            clock="11:00",
        )
        response = self._reschedule(
            self.patient_token, appointment_id, "11:00"
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["error"]["code"], "APPOINTMENT_SLOT_BOOKED"
        )
        stored = _get_appointment(appointment_id)
        self.assertEqual(
            stored["appointment_time"], datetime(2026, 10, 10, 9, 0)
        )


if __name__ == "__main__":
    unittest.main()
