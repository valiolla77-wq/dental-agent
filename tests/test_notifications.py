"""In-app notification inbox: event fan-out, reminders, read state."""

import asyncio
import os
import unittest
from datetime import datetime, time, timedelta

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["CONFIRMATION_HMAC_SECRET"] = "test-confirmation-hmac-secret-32-chars-long"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_dental_service import doctor_dental_services  # noqa: E402
from app.models.doctor_schedule import DoctorSchedule  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.appointment_service import clinic_now  # noqa: E402
from app.services.booking_service import create_booking  # noqa: E402
from app.utils.date_utils import gregorian_to_jalali  # noqa: E402

PHONE_BASE = "09360005"
DOCTOR_PHONE = PHONE_BASE + "001"
PATIENT_PHONE = PHONE_BASE + "002"
OTHER_PATIENT_PHONE = PHONE_BASE + "003"
RECEPTIONIST_PHONE = PHONE_BASE + "004"
ADMIN_PHONE = PHONE_BASE + "005"
PATIENT_NATIONAL_ID = "9500000021"
OTHER_NATIONAL_ID = "9500000022"


def _run(coro):
    return asyncio.run(coro)


def _next_saturday_slot() -> datetime:
    """Next 09:00 slot (Tehran wall clock) falling on day_of_week=0."""
    current = clinic_now()
    target = current.date()
    # Saturday is weekday()==5 in Python terms.
    days_ahead = (5 - target.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    slot = datetime.combine(target + timedelta(days=days_ahead), time(9, 0))
    if slot <= current:
        slot = slot + timedelta(days=7)
    return slot


class NotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.ids = _run(self._seed())

    def tearDown(self):
        _run(self._cleanup())

    async def _seed(self):
        async with SessionLocal() as db:
            service = DentalService(name="خدمت تست اعلان", is_active=True)
            db.add(service)
            await db.flush()

            doctor = Doctor(
                full_name="دکتر اعلان",
                specialty="تخصص اعلان",
                phone=DOCTOR_PHONE,
                is_active=True,
                dental_services=[service],
            )
            db.add(doctor)
            await db.flush()

            admin = User(
                full_name="مدیر اعلان",
                phone=ADMIN_PHONE,
                password_hash=hash_password("admin-pass-123"),
                role="admin",
                is_active=True,
            )
            receptionist = User(
                full_name="پذیرش اعلان",
                phone=RECEPTIONIST_PHONE,
                password_hash=hash_password("reception-pass-123"),
                role="receptionist",
                is_active=True,
            )
            patient_user = User(
                full_name="بیمار اعلان",
                phone=PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            other_user = User(
                full_name="بیمار دیگر اعلان",
                phone=OTHER_PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            db.add_all([admin, receptionist, patient_user, other_user])
            await db.flush()

            patient = Patient(
                national_id=PATIENT_NATIONAL_ID,
                full_name="بیمار اعلان",
                phone=PATIENT_PHONE,
                user_id=patient_user.id,
                is_account_holder=True,
            )
            other_patient = Patient(
                national_id=OTHER_NATIONAL_ID,
                full_name="بیمار دیگر اعلان",
                phone=OTHER_PATIENT_PHONE,
                user_id=other_user.id,
                is_account_holder=True,
            )
            db.add_all([patient, other_patient])
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
            await db.commit()
            return {
                "admin_id": admin.id,
                "admin_user_id": admin.id,
                "receptionist_user_id": receptionist.id,
                "doctor_id": doctor.id,
                "service_id": service.id,
                "patient_user_id": patient_user.id,
                "patient_id": patient.id,
                "other_user_id": other_user.id,
                "other_patient_id": other_patient.id,
            }

    async def _cleanup(self):
        async with SessionLocal() as db:
            patient_ids = (
                await db.execute(
                    select(Patient.id).where(
                        Patient.phone.in_([PATIENT_PHONE, OTHER_PATIENT_PHONE])
                    )
                )
            ).scalars().all()
            user_ids = (
                await db.execute(
                    select(User.id).where(
                        User.phone.in_(
                            [
                                DOCTOR_PHONE,
                                PATIENT_PHONE,
                                OTHER_PATIENT_PHONE,
                                RECEPTIONIST_PHONE,
                                ADMIN_PHONE,
                            ]
                        )
                    )
                )
            ).scalars().all()
            if patient_ids:
                await db.execute(
                    delete(Appointment).where(
                        Appointment.patient_id.in_(patient_ids)
                    )
                )
            if user_ids:
                await db.execute(
                    delete(Notification).where(
                        Notification.user_id.in_(user_ids)
                    )
                )
                await db.execute(
                    delete(Patient).where(Patient.user_id.in_(user_ids))
                )
                await db.execute(
                    delete(doctor_dental_services).where(
                        doctor_dental_services.c.doctor_id.in_(
                            select(Doctor.id).where(
                                Doctor.phone == DOCTOR_PHONE
                            )
                        )
                    )
                )
                await db.execute(
                    delete(DoctorSchedule).where(
                        DoctorSchedule.doctor_id.in_(
                            select(Doctor.id).where(
                                Doctor.phone == DOCTOR_PHONE
                            )
                        )
                    )
                )
                await db.execute(
                    delete(Doctor).where(Doctor.phone == DOCTOR_PHONE)
                )
                await db.execute(
                    delete(DentalService).where(
                        DentalService.name == "خدمت تست اعلان"
                    )
                )
                await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()

    def _auth(self, role):
        user_id = self.ids[f"{role}_user_id"]
        token = create_access_token(subject=str(user_id))
        return {"Authorization": f"Bearer {token}"}

    def test_staff_booking_notifies_patient_account(self):
        slot = _next_saturday_slot()
        jalali_date, jalali_time = gregorian_to_jalali(slot)

        booked = self.client.post(
            "/appointments/",
            json={
                "patient_id": self.ids["patient_id"],
                "doctor_id": self.ids["doctor_id"],
                "service_id": self.ids["service_id"],
                "appointment_date": jalali_date,
                "appointment_time": jalali_time,
            },
            headers=self._auth("receptionist"),
        )
        self.assertEqual(booked.status_code, 200, booked.text)

        inbox = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        self.assertGreaterEqual(inbox["unread_count"], 1)
        booked_items = [
            item
            for item in inbox["items"]
            if item["kind"] == "appointment_booked"
        ]
        self.assertEqual(len(booked_items), 1)
        self.assertIn("بیمار اعلان", booked_items[0]["body"])
        self.assertFalse(booked_items[0]["is_read"])

    def test_patient_cancellation_notifies_staff(self):
        slot = _next_saturday_slot()
        _run(self._book(slot, actor_role="patient"))

        cancelled = self.client.post(
            f"/appointments/{self._last_booked_id}/cancel",
            headers=self._auth("patient"),
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)

        staff_inbox = self.client.get(
            "/notifications/me", headers=self._auth("admin")
        ).json()
        cancelled_items = [
            item
            for item in staff_inbox["items"]
            if item["kind"] == "appointment_cancelled"
        ]
        self.assertEqual(len(cancelled_items), 1)
        self.assertIn("بیمار اعلان", cancelled_items[0]["body"])

        # The patient account must NOT receive a self-inflicted notice.
        patient_inbox = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        self.assertEqual(
            [
                item
                for item in patient_inbox["items"]
                if item["kind"] == "appointment_cancelled"
            ],
            [],
        )

    async def _book(self, slot: datetime, *, actor_role: str):
        async with SessionLocal() as db:
            appointment = await create_booking(
                db,
                doctor_id=self.ids["doctor_id"],
                service_id=self.ids["service_id"],
                appointment_date=gregorian_to_jalali(slot)[0],
                appointment_time=gregorian_to_jalali(slot)[1],
                patient_id=self.ids["patient_id"],
                actor_role=actor_role,
            )
            self._last_booked_id = appointment.id
            return appointment.id

    def test_mark_read_and_read_all(self):
        slot = _next_saturday_slot()
        _run(self._book(slot, actor_role="receptionist"))

        inbox = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        booked_items = [
            item
            for item in inbox["items"]
            if item["kind"] == "appointment_booked" and not item["is_read"]
        ]
        self.assertEqual(len(booked_items), 1)
        notification_id = booked_items[0]["id"]

        marked = self.client.post(
            f"/notifications/{notification_id}/read",
            headers=self._auth("patient"),
        )
        self.assertEqual(marked.status_code, 200, marked.text)

        inbox = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        still_unread = [
            item
            for item in inbox["items"]
            if item["kind"] == "appointment_booked" and not item["is_read"]
        ]
        self.assertEqual(still_unread, [])

    def test_foreign_notification_is_not_readable(self):
        # A notification owned by the admin account.
        async def _add_admin_notification():
            async with SessionLocal() as db:
                row = Notification(
                    user_id=self.ids["admin_id"],
                    kind="system",
                    title="اعلان مدیر",
                    is_read=False,
                )
                db.add(row)
                await db.commit()
                await db.refresh(row)
                return row.id

        foreign_id = _run(_add_admin_notification())
        stolen = self.client.post(
            f"/notifications/{foreign_id}/read",
            headers=self._auth("patient"),
        )
        self.assertEqual(stolen.status_code, 404)

    def test_reminder_created_once_for_tomorrows_appointment(self):
        soon = clinic_now() + timedelta(hours=3)

        async def _add_soon_appointment():
            async with SessionLocal() as db:
                appointment = Appointment(
                    patient_id=self.ids["patient_id"],
                    doctor_id=self.ids["doctor_id"],
                    service_id=self.ids["service_id"],
                    appointment_time=soon,
                    status="scheduled",
                )
                db.add(appointment)
                await db.commit()
                await db.refresh(appointment)
                return appointment.id

        _run(_add_soon_appointment())

        first = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        reminders = [
            item for item in first["items"] if item["kind"] == "reminder"
        ]
        self.assertEqual(len(reminders), 1)

        second = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        reminders_second = [
            item for item in second["items"] if item["kind"] == "reminder"
        ]
        self.assertEqual(len(reminders_second), 1)

    def test_read_all_clears_unread_counter(self):
        slot = _next_saturday_slot()
        _run(self._book(slot, actor_role="receptionist"))
        soon = clinic_now() + timedelta(hours=2)

        async def _add_soon_appointment():
            async with SessionLocal() as db:
                appointment = Appointment(
                    patient_id=self.ids["patient_id"],
                    doctor_id=self.ids["doctor_id"],
                    service_id=self.ids["service_id"],
                    appointment_time=soon,
                    status="scheduled",
                )
                db.add(appointment)
                await db.commit()

        _run(_add_soon_appointment())

        inbox = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        self.assertGreaterEqual(inbox["unread_count"], 2)

        cleared = self.client.post(
            "/notifications/read-all", headers=self._auth("patient")
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)

        inbox = self.client.get(
            "/notifications/me", headers=self._auth("patient")
        ).json()
        self.assertEqual(inbox["unread_count"], 0)


if __name__ == "__main__":
    unittest.main()
