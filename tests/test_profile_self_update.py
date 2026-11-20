"""Self-service profile rename (PUT /users/me) with audit coverage."""

import asyncio
import os
import unittest

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth.security import create_access_token, hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.user import User  # noqa: E402

PHONE_BASE = "09360006"
PATIENT_PHONE = PHONE_BASE + "001"
RECEPTIONIST_PHONE = PHONE_BASE + "002"


def _run(coro):
    return asyncio.run(coro)


class ProfileSelfUpdateTests(unittest.TestCase):
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
            patient = User(
                full_name="بیمار پروفایل",
                phone=PATIENT_PHONE,
                password_hash=hash_password("patient-pass-123"),
                role="patient",
                is_active=True,
            )
            receptionist = User(
                full_name="پذیرش پروفایل",
                phone=RECEPTIONIST_PHONE,
                password_hash=hash_password("reception-pass-123"),
                role="receptionist",
                is_active=True,
            )
            db.add_all([patient, receptionist])
            await db.commit()
            await db.refresh(patient)
            await db.refresh(receptionist)
            return {
                "patient_user_id": patient.id,
                "receptionist_user_id": receptionist.id,
            }

    async def _cleanup(self):
        async with SessionLocal() as db:
            user_ids = (
                await db.execute(
                    select(User.id).where(
                        User.phone.in_([PATIENT_PHONE, RECEPTIONIST_PHONE])
                    )
                )
            ).scalars().all()
            if user_ids:
                await db.execute(
                    delete(AuditLog).where(
                        AuditLog.action == "user.self_update"
                    )
                )
                await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()

    def _auth(self, role):
        token = create_access_token(subject=str(self.ids[f"{role}_user_id"]))
        return {"Authorization": f"Bearer {token}"}

    def test_patient_renames_own_account(self):
        response = self.client.put(
            "/users/me",
            json={"full_name": "بیمار تغییرنام‌ یافته"},
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["full_name"], "بیمار تغییرنام‌ یافته")

        me = self.client.get("/auth/me", headers=self._auth("patient"))
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["full_name"], "بیمار تغییرنام‌ یافته")

    def test_staff_renames_own_account(self):
        response = self.client.put(
            "/users/me",
            json={"full_name": "پذیرش ارتقایافته"},
            headers=self._auth("receptionist"),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_short_name_rejected(self):
        response = self.client.put(
            "/users/me",
            json={"full_name": "ab"},
            headers=self._auth("patient"),
        )
        self.assertEqual(response.status_code, 422)

    def test_rename_requires_authentication(self):
        response = self.client.put(
            "/users/me", json={"full_name": "بی‌توکن آزمایشی"}
        )
        self.assertEqual(response.status_code, 401)

    def test_rename_is_audited(self):
        self.client.put(
            "/users/me",
            json={"full_name": "بیمار ممیزی‌شده"},
            headers=self._auth("patient"),
        )

        async def _rows():
            async with SessionLocal() as db:
                result = await db.execute(
                    select(AuditLog).where(AuditLog.action == "user.self_update")
                )
                return result.scalars().all()

        rows = _run(_rows())
        self.assertEqual(len(rows), 1)
        detail = rows[0].detail or {}
        self.assertIn("full_name", detail)
        self.assertEqual(detail["full_name"]["to"], "بیمار ممیزی‌شده")

    def test_admin_update_endpoint_still_admin_only(self):
        response = self.client.put(
            f"/users/{self.ids['patient_user_id']}",
            json={"full_name": "هک آزمایشی"},
            headers=self._auth("patient"),
        )
        self.assertIn(response.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
