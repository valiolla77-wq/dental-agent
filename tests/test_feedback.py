"""Authenticated error-report and suggestion endpoints."""

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
from app.models.feedback import FeedbackReport  # noqa: E402
from app.models.user import User  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.admin_phone = "09360002201"
        self.patient_phone = "09360002202"
        self._cleanup()
        self.admin = _run(self._create_user(self.admin_phone, "admin"))
        self.patient = _run(self._create_user(self.patient_phone, "patient"))
        self.admin_token = create_access_token(subject=str(self.admin.id))
        self.patient_token = create_access_token(subject=str(self.patient.id))

    def tearDown(self):
        self._cleanup()

    async def _create_user(self, phone, role):
        async with SessionLocal() as db:
            user = User(
                full_name="Feedback Probe",
                phone=phone,
                password_hash=hash_password("probe-pass-123"),
                role=role,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    def _cleanup(self):
        async def _remove():
            async with SessionLocal() as db:
                phones = [self.admin_phone, self.patient_phone]
                users = (
                    await db.execute(select(User.id).where(User.phone.in_(phones)))
                ).scalars().all()
                if users:
                    await db.execute(
                        delete(FeedbackReport).where(
                            FeedbackReport.user_id.in_(users)
                        )
                    )
                    await db.execute(delete(User).where(User.id.in_(users)))
                await db.commit()

        _run(_remove())

    def _auth(self, token):
        return {"Authorization": f"Bearer {token}"}

    def _report_count(self):
        async def _count():
            async with SessionLocal() as db:
                rows = (
                    await db.execute(
                        select(FeedbackReport).where(
                            FeedbackReport.user_id == self.patient.id
                        )
                    )
                ).scalars().all()
                return rows

        return _run(_count())

    def test_error_report_stores_message_context_and_logs(self):
        response = self.client.post(
            "/feedback/",
            json={
                "category": "error",
                "message": "پاسخ دستیار ناقص بود",
                "session_id": "feedback-session",
                "page": "/agent",
                "assistant_message": "**ناقص**",
                "user_message": "نوبت می‌خواهم",
                "request_id": "req-123",
            },
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["status"], "received")
        self.assertIn("گزارش خطا", body["message"])

        rows = self._report_count()
        self.assertEqual(len(rows), 1)
        report = rows[0]
        self.assertEqual(report.category, "error")
        self.assertEqual(report.message, "پاسخ دستیار ناقص بود")
        self.assertEqual(report.context["role"], "patient")
        self.assertEqual(report.context["session_id"], "feedback-session")
        self.assertEqual(report.context["request_id"], "req-123")
        self.assertIsNotNone(report.logs)

    def test_suggestion_is_stored_without_logs(self):
        response = self.client.post(
            "/feedback/",
            json={"category": "suggestion", "message": "دکمه‌ها بزرگ‌تر شوند"},
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(response.status_code, 201, response.text)
        rows = self._report_count()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].category, "suggestion")
        self.assertIsNone(rows[0].logs)

    def test_feedback_requires_authentication(self):
        response = self.client.post(
            "/feedback/",
            json={"category": "error", "message": "x"},
        )
        self.assertEqual(response.status_code, 401)

    def test_feedback_list_is_admin_only(self):
        created = self.client.post(
            "/feedback/",
            json={"category": "error", "message": "خطای آزمایشی"},
            headers=self._auth(self.patient_token),
        )
        self.assertEqual(created.status_code, 201, created.text)

        denied = self.client.get(
            "/feedback/", headers=self._auth(self.patient_token)
        )
        self.assertEqual(denied.status_code, 403)

        allowed = self.client.get("/feedback/", headers=self._auth(self.admin_token))
        self.assertEqual(allowed.status_code, 200, allowed.text)
        ids = [row["id"] for row in allowed.json()]
        self.assertIn(created.json()["id"], ids)


if __name__ == "__main__":
    unittest.main()
