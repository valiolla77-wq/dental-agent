"""HTTP tests for the management APIs added for the role-aware web UI.

Covers: doctor catalog reads (auth required, phone never disclosed), admin
user listing/maintenance with self-lockout guards, patient search scoping,
role-scoped appointment listings (staff/doctor/patient), the doctor-user
link flow, and ``GET /auth/me``.
"""

import os
import unittest
from datetime import datetime
from datetime import time as time_cls

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.auth.security import create_access_token  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_schedule import DoctorSchedule  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402

DOCTOR_PHONE = "09220000100"
DOCTOR_PHONE_2 = "09220000101"
ADMIN_PHONE = "09220000001"
RECEPTION_PHONE = "09220000002"
DOCTOR_USER_PHONE = "09220000003"
PATIENT_PHONE = "09220000010"
OTHER_PATIENT_PHONE = "09220000011"


async def _seed_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    admin = User(id=1, full_name="مدیر", phone=ADMIN_PHONE,
                 password_hash="hash", role="admin", is_active=True)
    reception = User(id=2, full_name="پذیرش", phone=RECEPTION_PHONE,
                     password_hash="hash", role="receptionist", is_active=True)
    doctor_user = User(id=3, full_name="دکتر حساب", phone=DOCTOR_USER_PHONE,
                       password_hash="hash", role="doctor", is_active=True)
    other_doctor_user = User(id=4, full_name="حساب بدون رکورد",
                             phone="09220000004",
                             password_hash="hash", role="doctor", is_active=True)
    doctor_user_2 = User(id=5, full_name="دکتر حساب دوم", phone=DOCTOR_PHONE_2,
                         password_hash="hash", role="doctor", is_active=True)
    patient_user = User(id=10, full_name="بیمار الف", phone=PATIENT_PHONE,
                        password_hash="hash", role="patient", is_active=True)
    other_patient_user = User(id=11, full_name="بیمار ب", phone=OTHER_PATIENT_PHONE,
                              password_hash="hash", role="patient", is_active=True)
    inactive = User(id=12, full_name="غیرفعال", phone="09220000012",
                    password_hash="hash", role="patient", is_active=False)
    session.add_all(
        [admin, reception, doctor_user, other_doctor_user, doctor_user_2,
         patient_user, other_patient_user, inactive]
    )
    await session.flush()

    patient = Patient(id=500, national_id="1000000000",
                      full_name="بیمار الف نمونه", phone=PATIENT_PHONE,
                      user_id=patient_user.id)
    other_patient = Patient(id=501, national_id="1000000001",
                            full_name="دیگر نمونه", phone=OTHER_PATIENT_PHONE,
                            user_id=other_patient_user.id)
    doctor = Doctor(id=600, full_name="دکتر نمونه", specialty="عمومی",
                    phone=DOCTOR_PHONE, is_active=True, user_id=doctor_user.id)
    doctor_2 = Doctor(id=601, full_name="دکتر دوم", specialty="ارتدنسی",
                      phone=DOCTOR_PHONE_2, is_active=True)
    inactive_doctor = Doctor(id=602, full_name="دکتر غیرفعال", specialty="جرمی",
                             phone="09220000102", is_active=False)
    service = DentalService(id=700, name="معاینه نمونه", description=None,
                            is_active=True)
    session.add_all([patient, other_patient, doctor, doctor_2, inactive_doctor, service])
    await session.flush()
    session.add_all(
        [
            DoctorSchedule(
                id=800, doctor_id=600, day_of_week=0,
                start_time=time_cls(9, 0), end_time=time_cls(17, 0),
                slot_duration_minutes=30, is_active=True,
            ),
            Appointment(
                id=900, patient_id=500, doctor_id=600, service_id=700,
                appointment_time=datetime(2026, 10, 10, 10, 0),
                status="scheduled", reason=None,
            ),
            Appointment(
                id=901, patient_id=501, doctor_id=601, service_id=700,
                appointment_time=datetime(2026, 10, 10, 11, 0),
                status="scheduled", reason=None,
            ),
            Appointment(
                id=902, patient_id=500, doctor_id=600, service_id=700,
                appointment_time=datetime(2026, 10, 11, 9, 0),
                status="cancelled", reason=None,
            ),
        ]
    )
    await session.commit()
    return session, engine


class ManagementApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session, self.engine = await _seed_db()

        async def _override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)
        self.tokens = {
            "admin": create_access_token(subject="1"),
            "receptionist": create_access_token(subject="2"),
            "doctor": create_access_token(subject="3"),
            "doctor_unlinked": create_access_token(subject="4"),
            "patient": create_access_token(subject="10"),
            "other_patient": create_access_token(subject="11"),
        }
        self.headers = lambda token: {"Authorization": f"Bearer {token}"}

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_db, None)
        await self.session.close()
        await self.engine.dispose()

    def _get(self, path, token=None):
        return self.client.get(
            path, headers=self.headers(token) if token else {}
        )

    def _post(self, path, token, json):
        return self.client.post(path, headers=self.headers(token), json=json)

    def _put(self, path, token, json):
        return self.client.put(path, headers=self.headers(token), json=json)

    # --- Doctor catalog ---

    async def test_doctor_list_requires_authentication(self):
        self.assertEqual(self._get("/doctors/").status_code, 401)

    async def test_doctor_list_hides_phone_and_honors_active_only(self):
        response = self._get("/doctors/", self.tokens["patient"])
        self.assertEqual(response.status_code, 200, response.text)
        doctors = response.json()
        self.assertEqual(len(doctors), 2)  # only the two active ones
        for doctor in doctors:
            self.assertNotIn("phone", doctor)
            self.assertNotIn(DOCTOR_PHONE, response.text)
        self.assertEqual(
            {doctor["full_name"] for doctor in doctors},
            {"دکتر نمونه", "دکتر دوم"},
        )

    async def test_doctor_detail_hides_phone_and_reports_missing(self):
        response = self._get("/doctors/600", self.tokens["receptionist"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "دکتر نمونه")
        self.assertNotIn(DOCTOR_PHONE, response.text)

        response = self._get("/doctors/602", self.tokens["receptionist"])
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

        response = self._get("/doctors/9999", self.tokens["receptionist"])
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "DOCTOR_NOT_FOUND")

    async def test_doctor_link_requires_admin_and_matching_phone(self):
        response = self._post(
            "/doctors/601/link-user", self.tokens["receptionist"],
            {"phone": DOCTOR_PHONE_2},
        )
        self.assertEqual(response.status_code, 403)

        # Wrong role account: rejected even with a matching phone.
        response = self._post(
            "/doctors/601/link-user", self.tokens["admin"],
            {"phone": PATIENT_PHONE},
        )
        self.assertEqual(response.status_code, 422)

        # Mismatched phone: rejected.
        response = self._post(
            "/doctors/601/link-user", self.tokens["admin"],
            {"phone": "09999999999"},
        )
        self.assertEqual(response.status_code, 422)

        # Happy path, then link uniqueness is enforced.
        response = self._post(
            "/doctors/601/link-user", self.tokens["admin"],
            {"phone": DOCTOR_PHONE_2},
        )
        self.assertEqual(response.status_code, 200, response.text)
        stored = (await self.session.execute(
            select(Doctor).where(Doctor.id == 601)
        )).scalar_one()
        self.assertEqual(stored.user_id, 5)

        response = self._post(
            "/doctors/601/link-user", self.tokens["admin"],
            {"phone": DOCTOR_PHONE_2},
        )
        self.assertEqual(response.status_code, 409)

    # --- User management ---

    async def test_user_list_is_admin_only(self):
        response = self._get("/users/", self.tokens["admin"])
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertGreaterEqual(len(payload), 7)
        for user in payload:
            self.assertNotIn("password_hash", user)

        self.assertEqual(self._get("/users/", self.tokens["receptionist"]).status_code, 403)
        self.assertEqual(self._get("/users/", self.tokens["patient"]).status_code, 403)

    async def test_admin_can_deactivate_and_reactivate_account(self):
        response = self._put("/users/12", self.tokens["admin"], {"is_active": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["is_active"])

        response = self._put("/users/12", self.tokens["admin"], {"is_active": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["is_active"])

    async def test_admin_self_lockout_is_rejected(self):
        response = self._put("/users/1", self.tokens["admin"], {"is_active": False})
        self.assertEqual(response.status_code, 409)
        response = self._put("/users/1", self.tokens["admin"], {"role": "receptionist"})
        self.assertEqual(response.status_code, 409)

    async def test_user_management_is_admin_only(self):
        response = self._put(
            "/users/12", self.tokens["receptionist"], {"is_active": True}
        )
        self.assertEqual(response.status_code, 403)
        response = self._put(
            "/users/12", self.tokens["patient"], {"full_name": "هک"}
        )
        self.assertEqual(response.status_code, 403)
        response = self._put(
            "/users/999", self.tokens["admin"], {"is_active": True}
        )
        self.assertEqual(response.status_code, 404)

    # --- Patient search scoping ---

    async def test_staff_can_search_patients(self):
        response = self._get(
            "/patients/?search=%D8%A8%DB%8C%D9%85%D8%A7%D8%B1%20%D8%A7%D9%84%D9%81",
            self.tokens["receptionist"],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], 500)

        response = self._get(
            f"/patients/?search={OTHER_PATIENT_PHONE}", self.tokens["doctor"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [501])

    async def test_patient_search_is_ignored_and_scope_stays_self(self):
        response = self._get(
            f"/patients/?search={OTHER_PATIENT_PHONE}", self.tokens["patient"]
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["id"] for row in response.json()], [500])

    async def test_patient_search_is_rejected_for_doctor_unlinked_and_anon(self):
        # Unlinked patient accounts get an empty list, never a leak.
        response = self._get("/patients/?search=x", self.tokens["patient"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], 500)

        self.assertEqual(
            self._get("/patients/?search=x").status_code, 401
        )

    # --- Appointment listings ---

    async def test_staff_listing_sees_all_and_filters(self):
        response = self._get("/appointments/", self.tokens["admin"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 3)
        first = response.json()[0]
        for field in ("patient_name", "doctor_name", "service_name",
                      "appointment_date", "appointment_time", "status"):
            self.assertIn(field, first)

        response = self._get(
            "/appointments/?status=cancelled", self.tokens["receptionist"]
        )
        self.assertEqual([row["id"] for row in response.json()], [902])

        response = self._get(
            "/appointments/?doctor_id=600", self.tokens["receptionist"]
        )
        self.assertEqual([row["id"] for row in response.json()], [902, 900])

        response = self._get(
            "/appointments/?status=weird", self.tokens["admin"]
        )
        self.assertEqual(response.status_code, 422)

    async def test_doctor_listing_is_scoped_to_linked_record(self):
        response = self._get("/appointments/", self.tokens["doctor"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            {row["doctor_id"] for row in response.json()}, {600}
        )

        # Passing another doctor's id cannot widen the scope.
        response = self._get(
            "/appointments/?doctor_id=601", self.tokens["doctor"]
        )
        self.assertEqual(response.status_code, 403)

        # Unlinked doctor accounts get no listing at all.
        response = self._get("/appointments/", self.tokens["doctor_unlinked"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["error"]["code"], "DOCTOR_ACCOUNT_NOT_LINKED"
        )

    async def test_patient_is_rejected_on_staff_listing(self):
        response = self._get("/appointments/", self.tokens["patient"])
        self.assertEqual(response.status_code, 403)

    async def test_patient_me_listing_resolves_own_record(self):
        response = self._get("/appointments/me", self.tokens["patient"])
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual(
            {row["patient_id"] for row in rows}, {500}
        )
        self.assertTrue(
            all(row["patient_name"] == "بیمار الف نمونه" for row in rows)
        )

        # Another patient gets their own list only.
        response = self._get("/appointments/me", self.tokens["other_patient"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {row["patient_id"] for row in response.json()}, {501}
        )

        # Staff have no self-listing.
        self.assertEqual(
            self._get("/appointments/me", self.tokens["admin"]).status_code, 403
        )

    # --- /auth/me ---

    async def test_me_reflects_role_and_own_links(self):
        response = self._get("/auth/me", self.tokens["patient"])
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["role"], "patient")
        self.assertEqual(payload["patient"]["id"], 500)
        self.assertIsNone(payload["doctor"])

        response = self._get("/auth/me", self.tokens["doctor"])
        payload = response.json()
        self.assertEqual(payload["role"], "doctor")
        self.assertEqual(payload["doctor"]["id"], 600)
        self.assertIsNone(payload["patient"])

        response = self._get("/auth/me", self.tokens["admin"])
        payload = response.json()
        self.assertEqual(payload["role"], "admin")
        self.assertIsNone(payload["patient"])
        self.assertIsNone(payload["doctor"])

        self.assertEqual(self._get("/auth/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()
