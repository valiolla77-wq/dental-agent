"""HTTP regression tests for staff-assisted user linking and cross-user IDOR guards.

The FastAPI app is exercised through TestClient while ``get_db`` is overridden
to yield a seeded in-memory session, so both router authorization and the
underlying permission policy are covered end to end.
"""

import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.auth.security import create_access_token  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.user import User  # noqa: E402


async def _seed_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    user_a = User(id=100, full_name="patient a", phone="09110000100",
                  password_hash="hash", role="patient", is_active=True)
    user_b = User(id=101, full_name="patient b", phone="09110000101",
                  password_hash="hash", role="patient", is_active=True)
    admin = User(id=1, full_name="clinic admin", phone="09110000001",
                 password_hash="hash", role="admin", is_active=True)
    record_a = Patient(id=500, national_id="1000000000", full_name="record a",
                       phone="09110000100", user_id=100)
    record_b = Patient(id=501, national_id="1000000001", full_name="record b",
                       phone="09110000101", user_id=None)
    appt_a = Appointment(id=700, patient_id=500, doctor_id=1, service_id=1,
                         appointment_time=datetime(2026, 10, 10, 10, 0),
                         status="scheduled")
    session.add_all([user_a, user_b, admin, record_a, record_b, appt_a])
    await session.commit()
    for obj in (user_a, user_b, admin, record_a, record_b, appt_a):
        await session.refresh(obj)
    return session, engine


def _await(coro):
    """Run one coroutine on a fresh loop (sync unittest context)."""
    return asyncio.run(coro)


class LinkAndIdorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session, self.engine = await _seed_db()

        async def _override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)
        self.token_a = create_access_token(subject="100")
        self.token_b = create_access_token(subject="101")
        self.token_admin = create_access_token(subject="1")
        self.headers = lambda token: {"Authorization": f"Bearer {token}"}

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_db, None)
        await self.session.close()
        await self.engine.dispose()

    def _get(self, path, token):
        return self.client.get(path, headers=self.headers(token))

    def _put(self, path, token, json):
        return self.client.put(path, headers=self.headers(token), json=json)

    def _post(self, path, token, json):
        return self.client.post(path, headers=self.headers(token), json=json)

    async def test_patient_sees_own_record_before_link(self):
        response = self._get("/patients/500", self.token_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 500)

    async def test_unlinked_patient_cannot_read_another_record(self):
        response = self._get("/patients/500", self.token_b)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PATIENT_ACCOUNT_NOT_LINKED")

    async def test_unauthenticated_is_rejected(self):
        response = self.client.get("/patients/500")
        self.assertEqual(response.status_code, 401)

    async def test_admin_can_link_user_and_ownership_transfers(self):
        # An orphan record can be linked to a patient account.
        response = self._post(
            "/patients/501/link-user", self.token_admin,
            {"phone": "09110000101"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], 501)

        # The other patient (not linked to this record) is rejected.
        response = self._get("/patients/501", self.token_a)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "COMMON_FORBIDDEN")

        # The linked owner sees the record.
        response = self._get("/patients/501", self.token_b)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], 501)
        from sqlalchemy import select

        result = await self.session.execute(select(Patient).where(Patient.id == 501))
        self.assertEqual(result.scalar_one().user_id, 101)

        # Re-linking an already-linked record is rejected.
        response = self._post(
            "/patients/500/link-user", self.token_admin,
            {"phone": "09110000101"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "COMMON_CONFLICT")

    async def test_patient_cannot_update_another_record(self):
        response = self._put(
            "/patients/500", self.token_b,
            {"full_name": "hacked", "phone": "09110000101"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PATIENT_ACCOUNT_NOT_LINKED")

    async def test_patient_cannot_read_another_patient_appointments(self):
        response = self._get("/appointments/patient/500", self.token_b)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PATIENT_ACCOUNT_NOT_LINKED")

    async def test_owner_reads_own_appointments(self):
        response = self._get("/appointments/patient/500", self.token_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    async def test_patient_cannot_book_for_another_record(self):
        # Link user_b to record 501 first, then it must not book for record 500.
        self._post("/patients/501/link-user", self.token_admin, {"phone": "09110000101"})
        response = self._post(
            "/appointments/", self.token_b,
            {
                "patient_id": 500,
                "doctor_id": 1,
                "service_id": 1,
                "appointment_date": "2026-10-10",
                "appointment_time": "10:00",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "COMMON_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()