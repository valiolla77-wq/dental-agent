"""HTTP tests for the admin doctor-management read endpoints.

These are the only doctor reads that expose the phone (plus account and
service linkage). The public catalog contract (no phone, every role) is
locked by tests/test_catalog_privacy.py; this file locks the admin door.
"""

import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.auth.security import create_access_token  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.dental_service import DentalService  # noqa: E402
from app.models.doctor import Doctor  # noqa: E402
from app.models.doctor_dental_service import doctor_dental_services  # noqa: E402
from app.models.user import User  # noqa: E402

ADMIN_ID = 1
RECEPTION_ID = 2
DOCTOR_PHONE = "09330000010"
SERVICE_PHONE = "09330000011"


class DoctorManageReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        await self._seed()

        async def _override_get_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)

    async def asyncTearDown(self) -> None:
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()

    async def _seed(self) -> None:
        async with self.session_factory() as db:
            db.add_all(
                [
                    User(
                        id=ADMIN_ID,
                        full_name="مدیر",
                        phone="09330000001",
                        password_hash="hash",
                        role="admin",
                        is_active=True,
                    ),
                    User(
                        id=RECEPTION_ID,
                        full_name="پذیرش",
                        phone="09330000002",
                        password_hash="hash",
                        role="receptionist",
                        is_active=True,
                    ),
                    Doctor(
                        id=600,
                        full_name="دکتر نمونه",
                        specialty="عمومی",
                        phone=DOCTOR_PHONE,
                        is_active=True,
                        user_id=None,
                    ),
                    DentalService(
                        id=700,
                        name="جرم‌گیری",
                        description=None,
                        is_active=True,
                    ),
                ]
            )
            await db.flush()
            await db.execute(
                doctor_dental_services.insert().values(
                    doctor_id=600, dental_service_id=700
                )
            )
            await db.commit()

    def _headers(self, user_id: int) -> dict[str, str]:
        token = create_access_token(subject=str(user_id))
        return {"Authorization": f"Bearer {token}"}

    async def test_manage_listing_is_admin_only(self) -> None:
        response = self.client.get(
            "/doctors/manage", headers=self._headers(RECEPTION_ID)
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.get("/doctors/manage")
        self.assertEqual(response.status_code, 401)

    async def test_manage_listing_includes_contact_and_links(self) -> None:
        response = self.client.get(
            "/doctors/manage", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        doctor = payload[0]
        self.assertEqual(doctor["id"], 600)
        self.assertEqual(doctor["phone"], DOCTOR_PHONE)
        self.assertEqual(doctor["user_id"], None)
        self.assertEqual(doctor["service_ids"], [700])

    async def test_manage_detail_includes_contact_and_links(self) -> None:
        response = self.client.get(
            "/doctors/600/manage", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 200)
        doctor = response.json()
        self.assertEqual(doctor["phone"], DOCTOR_PHONE)
        self.assertEqual(doctor["service_ids"], [700])
        self.assertNotIn(DOCTOR_PHONE, "")

    async def test_manage_detail_is_admin_only(self) -> None:
        response = self.client.get(
            "/doctors/600/manage", headers=self._headers(RECEPTION_ID)
        )
        self.assertEqual(response.status_code, 403)

    async def test_manage_detail_404_for_missing(self) -> None:
        response = self.client.get(
            "/doctors/9999/manage", headers=self._headers(ADMIN_ID)
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
