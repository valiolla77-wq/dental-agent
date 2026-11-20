"""Post-visit satisfaction ratings: eligibility, uniqueness, summary."""

import asyncio
import os
import unittest
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.visit_rating import VisitRating  # noqa: E402
from app.services.appointment_service import clinic_now  # noqa: E402

PHONE_BASE = "09360007"
DOCTOR_PHONE = PHONE_BASE + "001"
PATIENT_PHONE = PHONE_BASE + "002"
OTHER_PATIENT_PHONE = PHONE_BASE + "003"
ADMIN_PHONE = PHONE_BASE + "004"
RECEPTIONIST_PHONE = PHONE_BASE + "005"


def _run(coro):
    return asyncio.run(coro)


class VisitRatingTests(unittest.TestCase):
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
            service = DentalService(name="خدمت تست رضایت", is_active=True)
            doctor = Doctor(
                full_name="دکتر رضایت",
                specialty="تخصص رضایت",
                phone=DOCTOR_PHONE,
                is_active=True,
            )
            admin = User(
                full_name="مدیر رضایت",
                phone=ADMIN_PHONE,
                password_hash=hash_password("admin-pass-123"),
                role="admin",
                is_active=True,
            )
            receptionist = User(
                full_name="پذیرش رضایت",
                phone=RECEPTIONIST_PHONE,
                password_hash=hash_password("reception-pass-123"),
                role="receptionist",
                is_active=True,
            )
            patient_user = User(
                full_name="بیمار رضایت",
                phone=PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            other_user = User(
                full_name="بیمار دیگر رضایت",
                phone=OTHER_PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            db.add_all(
                [service, doctor, admin, receptionist, patient_user, other_user]
            )
            await db.flush()

            patient = Patient(
                national_id="9600000031",
                full_name="بیمار رضایت",
                phone=PATIENT_PHONE,
                user_id=patient_user.id,
                is_account_holder=True,
            )
            other_patient = Patient(
                national_id="9600000032",
                full_name="بیمار دیگر رضایت",
                phone=OTHER_PATIENT_PHONE,
                user_id=other_user.id,
                is_account_holder=True,
            )
            db.add_all([patient, other_patient])
            await db.flush()

            past_time = clinic_now() - timedelta(days=3)
            past_other_time = past_time - timedelta(hours=2)
            future_time = clinic_now() + timedelta(days=7)
            past_own = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=past_time,
                status="scheduled",
            )
            cancelled_own = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=past_time + timedelta(hours=1),
                status="cancelled",
            )
            future_own = Appointment(
                patient_id=patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=future_time,
                status="scheduled",
            )
            past_other = Appointment(
                patient_id=other_patient.id,
                doctor_id=doctor.id,
                service_id=service.id,
                appointment_time=past_other_time,
                status="scheduled",
            )
            db.add_all([past_own, cancelled_own, future_own, past_other])
            await db.commit()
            return {
                "admin_user_id": admin.id,
                "receptionist_user_id": receptionist.id,
                "patient_user_id": patient_user.id,
                "past_appointment_id": past_own.id,
                "cancelled_appointment_id": cancelled_own.id,
                "future_appointment_id": future_own.id,
                "other_appointment_id": past_other.id,
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
                                ADMIN_PHONE,
                                RECEPTIONIST_PHONE,
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
            await db.execute(delete(VisitRating))
            if user_ids:
                await db.execute(
                    delete(Patient).where(Patient.user_id.in_(user_ids))
                )
                await db.execute(
                    delete(Doctor).where(Doctor.phone == DOCTOR_PHONE)
                )
                await db.execute(
                    delete(DentalService).where(
                        DentalService.name == "خدمت تست رضایت"
                    )
                )
                await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()

    def _auth(self, role):
        token = create_access_token(subject=str(self.ids[f"{role}_user_id"]))
        return {"Authorization": f"Bearer {token}"}

    def test_patient_rates_past_visit(self):
        response = self.client.post(
            "/visit-ratings/",
            json={
                "appointment_id": self.ids["past_appointment_id"],
                "rating": 5,
                "comment": "برخورد عالی بود",
            },
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["rating"], 5)

    def test_duplicate_rating_rejected(self):
        first = self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["past_appointment_id"], "rating": 4},
            headers=self._auth("patient"),
        )
        self.assertEqual(first.status_code, 201, first.text)

        second = self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["past_appointment_id"], "rating": 2},
            headers=self._auth("patient"),
        )
        self.assertEqual(second.status_code, 409)
        self.assertEqual(
            second.json()["error"]["code"], "VISIT_RATING_ALREADY_SUBMITTED"
        )

    def test_rating_bounds_enforced(self):
        response = self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["past_appointment_id"], "rating": 6},
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 422)

    def test_future_visit_not_rateable(self):
        response = self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["future_appointment_id"], "rating": 5},
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "VISIT_NOT_RATEABLE")

    def test_cancelled_visit_not_rateable(self):
        response = self.client.post(
            "/visit-ratings/",
            json={
                "appointment_id": self.ids["cancelled_appointment_id"],
                "rating": 5,
            },
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 409)

    def test_foreign_appointment_rejected(self):
        response = self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["other_appointment_id"], "rating": 5},
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_rate(self):
        response = self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["past_appointment_id"], "rating": 5},
            headers=self._auth("receptionist"),
        )
        self.assertEqual(response.status_code, 403)

    def test_my_ratings_listing(self):
        self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["past_appointment_id"], "rating": 3},
            headers=self._auth("patient"),
        )
        mine = self.client.get(
            "/visit-ratings/mine", headers=self._auth("patient")
        )
        self.assertEqual(mine.status_code, 200, mine.text)
        ids = [row["appointment_id"] for row in mine.json()]
        self.assertIn(self.ids["past_appointment_id"], ids)

    def test_summary_admin_only(self):
        self.client.post(
            "/visit-ratings/",
            json={"appointment_id": self.ids["past_appointment_id"], "rating": 4},
            headers=self._auth("patient"),
        )

        summary = self.client.get(
            "/visit-ratings/summary", headers=self._auth("admin")
        )
        self.assertEqual(summary.status_code, 200, summary.text)
        body = summary.json()
        self.assertGreaterEqual(body["count"], 1)
        self.assertTrue(1.0 <= body["average"] <= 5.0)

        denied = self.client.get(
            "/visit-ratings/summary", headers=self._auth("receptionist")
        )
        self.assertEqual(denied.status_code, 403)


if __name__ == "__main__":
    unittest.main()
