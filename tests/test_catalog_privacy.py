"""HTTP regression tests for doctor privacy in the clinic catalog (P0-1).

Service listings stay public for visitors, but doctor contact data (phone)
never leaves the server for non-admin callers, and operational catalog reads
(doctors of a service, services of a doctor, schedules) require an
authenticated user.
"""

import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from datetime import time as time_cls  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.auth.security import create_access_token  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_dental_service import doctor_dental_services  # noqa: E402
from app.models.doctor_schedule import DoctorSchedule  # noqa: E402
from app.models.user import User  # noqa: E402

DOCTOR_PHONE = "09123450000"


async def _seed_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    patient_user = User(
        id=300, full_name="patient", phone="09120000300",
        password_hash="hash", role="patient", is_active=True,
    )
    receptionist_user = User(
        id=301, full_name="reception", phone="09120000301",
        password_hash="hash", role="receptionist", is_active=True,
    )
    admin_user = User(
        id=302, full_name="admin", phone="09120000302",
        password_hash="hash", role="admin", is_active=True,
    )
    doctor = Doctor(
        id=600, full_name="دکتر نمونه", specialty="عمومی",
        phone=DOCTOR_PHONE, is_active=True,
    )
    service = DentalService(
        id=700, name="خدمت نمونه", description=None, is_active=True,
    )
    schedule = DoctorSchedule(
        id=800, doctor_id=600, day_of_week=0,
        start_time=time_cls(9, 0), end_time=time_cls(17, 0),
        slot_duration_minutes=30, is_active=True,
    )
    session.add_all(
        [patient_user, receptionist_user, admin_user, doctor, service, schedule]
    )
    await session.commit()
    await session.execute(
        doctor_dental_services.insert().values(
            doctor_id=600, dental_service_id=700
        )
    )
    await session.commit()
    return session, engine


class CatalogPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session, self.engine = await _seed_db()

        async def _override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)
        self.token_patient = create_access_token(subject="300")
        self.token_receptionist = create_access_token(subject="301")
        self.token_admin = create_access_token(subject="302")
        self.headers = lambda token: {"Authorization": f"Bearer {token}"}

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_db, None)
        await self.session.close()
        await self.engine.dispose()

    def _get(self, path, token=None):
        headers = self.headers(token) if token else {}
        return self.client.get(path, headers=headers)

    # --- Public service catalog (no PII, safe for visitors) ---

    async def test_service_catalog_is_public_and_has_no_phone(self):
        response = self._get("/dental-services/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("phone", response.text)
        response = self._get("/dental-services/700")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("phone", response.text)

    # --- Anonymous access is rejected on doctor/schedule reads ---

    async def test_anonymous_cannot_list_service_doctors(self):
        response = self._get("/dental-services/700/doctors")
        self.assertEqual(response.status_code, 401)

    async def test_anonymous_cannot_read_doctor_services(self):
        response = self._get("/doctors/600/services")
        self.assertEqual(response.status_code, 401)

    async def test_anonymous_cannot_read_doctor_schedules(self):
        response = self._get("/doctor-schedules/600")
        self.assertEqual(response.status_code, 401)

    # --- Authenticated reads succeed but never disclose the phone ---

    async def test_service_doctors_hide_phone_for_every_role(self):
        for token in (
            self.token_patient,
            self.token_receptionist,
            self.token_admin,
        ):
            response = self._get("/dental-services/700/doctors", token)
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            self.assertEqual(len(payload), 1)
            doctor = payload[0]
            self.assertEqual(doctor["id"], 600)
            self.assertEqual(doctor["full_name"], "دکتر نمونه")
            self.assertEqual(doctor["specialty"], "عمومی")
            self.assertTrue(doctor["is_active"])
            self.assertNotIn("phone", doctor)
            self.assertNotIn(DOCTOR_PHONE, response.text)

    async def test_admin_management_response_still_returns_phone(self):
        # Admin create/update keeps the full DoctorResponse (with phone) so
        # staff can manage contact data; only catalog reads are scrubbed.
        response = self.client.post(
            "/doctors/",
            headers=self.headers(self.token_admin),
            json={
                "full_name": "دکتر جدید",
                "specialty": "ارتدنسی",
                "phone": "09129990000",
                "service_ids": [],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["phone"], "09129990000")


if __name__ == "__main__":
    unittest.main()