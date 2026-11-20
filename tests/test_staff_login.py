"""HTTP tests for the separated patient/staff login portals.

Covers: the staff-only door (``POST /auth/staff/login``), the ``portal``
field on ``POST /auth/login``, patient-door rejection of staff accounts,
staff-door rejection of patient accounts, and the ``last_login_at``
bookkeeping stamp written on every successful password login.
"""

import os
import unittest
from datetime import UTC, datetime

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.auth.rate_limit import login_rate_limiter  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402

ADMIN_PHONE = "09310000001"
ADMIN_PASSWORD = "AdminPass!123"
PATIENT_PHONE = "09310000002"
PATIENT_PASSWORD = "PatientPass!123"


class StaffLoginPortalTests(unittest.TestCase):
    def setUp(self) -> None:
        login_rate_limiter.reset()

    def _make_client(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.session_factory = session_factory

        async def _override_get_db():
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        return TestClient(app)

    def _seed_sync(self) -> None:
        async def _seed():
            async with self.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with self.session_factory() as db:
                db.add(
                    User(
                        full_name="مدیر تست",
                        phone=ADMIN_PHONE,
                        password_hash=hash_password(ADMIN_PASSWORD),
                        role="admin",
                        is_active=True,
                    )
                )
                db.add(
                    User(
                        full_name="بیمار تست",
                        phone=PATIENT_PHONE,
                        password_hash=hash_password(PATIENT_PASSWORD),
                        role="patient",
                        is_active=True,
                    )
                )
                await db.commit()

        import asyncio

        asyncio.run(_seed())

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        import asyncio

        asyncio.run(self.engine.dispose())

    def test_staff_door_accepts_staff_account(self) -> None:
        client = self._make_client()
        self._seed_sync()
        response = client.post(
            "/auth/staff/login",
            json={"phone": ADMIN_PHONE, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_staff_door_rejects_patient_account(self) -> None:
        client = self._make_client()
        self._seed_sync()
        response = client.post(
            "/auth/staff/login",
            json={"phone": PATIENT_PHONE, "password": PATIENT_PASSWORD},
        )
        self.assertEqual(response.status_code, 403)
        body = response.json()
        self.assertEqual(body.get("error", {}).get("code"), "AUTH_PORTAL_MISMATCH")

    def test_staff_door_rejects_wrong_password_first(self) -> None:
        client = self._make_client()
        self._seed_sync()
        response = client.post(
            "/auth/staff/login",
            json={"phone": ADMIN_PHONE, "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

    def test_patient_portal_rejects_staff_account(self) -> None:
        client = self._make_client()
        self._seed_sync()
        response = client.post(
            "/auth/login",
            json={
                "phone": ADMIN_PHONE,
                "password": ADMIN_PASSWORD,
                "portal": "patient",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json().get("error", {}).get("code"),
            "AUTH_PORTAL_MISMATCH",
        )

    def test_staff_portal_rejects_patient_account(self) -> None:
        client = self._make_client()
        self._seed_sync()
        response = client.post(
            "/auth/login",
            json={
                "phone": PATIENT_PHONE,
                "password": PATIENT_PASSWORD,
                "portal": "staff",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_patient_portal_accepts_patient_account(self) -> None:
        client = self._make_client()
        self._seed_sync()
        response = client.post(
            "/auth/login",
            json={
                "phone": PATIENT_PHONE,
                "password": PATIENT_PASSWORD,
                "portal": "patient",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access_token", response.json())

    def test_login_without_portal_stays_compatible(self) -> None:
        """Legacy callers that omit ``portal`` keep working for both roles."""
        client = self._make_client()
        self._seed_sync()
        for phone, password in (
            (ADMIN_PHONE, ADMIN_PASSWORD),
            (PATIENT_PHONE, PATIENT_PASSWORD),
        ):
            response = client.post(
                "/auth/login", json={"phone": phone, "password": password}
            )
            self.assertEqual(response.status_code, 200)

    def test_successful_login_stamps_last_login(self) -> None:
        client = self._make_client()
        self._seed_sync()
        before = datetime.now(UTC).replace(tzinfo=None)
        response = client.post(
            "/auth/staff/login",
            json={"phone": ADMIN_PHONE, "password": ADMIN_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)

        async def _load():
            async with self.session_factory() as db:
                row = await db.scalar(select(User).where(User.phone == ADMIN_PHONE))
                return row.last_login_at

        import asyncio

        stamped = asyncio.run(_load())
        self.assertIsNotNone(stamped)
        self.assertGreaterEqual(stamped, before)


if __name__ == "__main__":
    unittest.main()
