"""OTP request/verify regression tests using the in-memory fake SMS channel."""

import asyncio
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

# Set test environment variables BEFORE importing app modules. The shared test
# database URL is read at import time by app.database.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import otp as otp_service  # noqa: E402
from app.auth.otp import _ip_requests  # noqa: E402
from app.auth.security import decode_access_token  # noqa: E402
from app.auth.sms import fake_sms  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402


def _await(coro):
    """Run one coroutine on a fresh loop (sync unittest context)."""
    return asyncio.run(coro)


def _run_db(coro_factory):
    async def _wrapper():
        async with SessionLocal() as db:
            return await coro_factory(db)

    return _await(_wrapper())


async def _delete_phone_user(phone):
    from sqlalchemy import delete

    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.phone == phone))
        await db.commit()


class OtpAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _await(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.phone = "09370001111"
        _run_db(lambda db: otp_service.purge_phone_codes(db, self.phone))
        _ip_requests.clear()
        fake_sms.outbox.pop(self.phone, None)

    @staticmethod
    def _db_session():
        # purge helper needs a session; open a short-lived one synchronously.
        import asyncio as _asyncio

        async def _noop():
            async with SessionLocal() as db:
                return db

        return _run(_noop())

    def _request_code(self, phone=None):
        response = self.client.post(
            "/auth/otp/request", json={"phone": phone or self.phone}
        )
        self.assertEqual(response.status_code, 202)
        return response.json()

    def _verify_code(self, phone, code):
        return self.client.post(
            "/auth/otp/verify", json={"phone": phone, "code": code}
        )

    def test_successful_otp_login_issues_jwt(self):
        body = self._request_code()
        self.assertEqual(body["status"], "accepted")
        self.assertTrue(body["dev_otp"])
        verify = self._verify_code(self.phone, body["dev_otp"])
        self.assertEqual(verify.status_code, 200)
        token = verify.json()["access_token"]
        payload = decode_access_token(token)
        self.assertTrue(payload["sub"])
        self.assertIn("exp", payload)

    def test_wrong_code_is_rejected_without_token(self):
        self._request_code()
        verify = self._verify_code(self.phone, "000000")
        self.assertEqual(verify.status_code, 401)
        self.assertEqual(verify.json()["error"]["code"], "COMMON_UNAUTHORIZED")

    def test_consumed_code_cannot_be_reused(self):
        body = self._request_code()
        first = self._verify_code(self.phone, body["dev_otp"])
        self.assertEqual(first.status_code, 200)
        second = self._verify_code(self.phone, body["dev_otp"])
        self.assertEqual(second.status_code, 401)

    def test_attempt_limit_locks_the_code(self):
        self._request_code()
        with patch.dict(os.environ, {"OTP_MAX_ATTEMPTS": "2"}):
            for _ in range(2):
                bad = self._verify_code(self.phone, "000000")
                self.assertEqual(bad.status_code, 401)
            # The code is now exhausted; even attempts read as invalid.
            locked = self._verify_code(self.phone, "000000")
            self.assertEqual(locked.status_code, 401)
            self.assertEqual(locked.json()["error"]["code"], "COMMON_UNAUTHORIZED")

    def test_resend_cooldown_rejects_immediate_second_request(self):
        self._request_code()
        with patch.dict(os.environ, {"OTP_RESEND_COOLDOWN_SECONDS": "3600"}):
            retry = self.client.post(
                "/auth/otp/request", json={"phone": self.phone}
            )
            self.assertEqual(retry.status_code, 429)

    def test_new_code_invalidates_previous_code(self):
        first = self._request_code()
        with patch.dict(os.environ, {"OTP_RESEND_COOLDOWN_SECONDS": "0"}):
            second = self._request_code()
        self.assertNotEqual(second["dev_otp"], first["dev_otp"])
        reuse = self._verify_code(self.phone, first["dev_otp"])
        self.assertEqual(reuse.status_code, 401)
        self.assertEqual(reuse.json()["error"]["code"], "COMMON_UNAUTHORIZED")

    def test_unknown_phone_gets_uniform_response_without_login(self):
        ghost = "09379998888"
        _run_db(lambda db: otp_service.purge_phone_codes(db, ghost))
        body = self._request_code(phone=ghost)
        self.assertEqual(body["status"], "accepted")
        self.assertTrue(body["dev_otp"])
        bad = self._verify_code(ghost, "000000")
        self.assertEqual(bad.status_code, 401)

    def test_staff_phone_is_never_authenticated_by_otp(self):
        phone = "09371112222"
        created = []

        async def _seed():
            from app.auth.security import hash_password

            async with SessionLocal() as db:
                user = User(
                    full_name="Staff",
                    phone=phone,
                    password_hash=hash_password("staff-pass-1"),
                    role="receptionist",
                    is_active=True,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                created.append(user.id)

        _await(_seed())
        try:
            body = self._request_code(phone=phone)
            self.assertIsNone(body["dev_otp"])
            bad = self._verify_code(phone, "000000")
            self.assertEqual(bad.status_code, 401)
        finally:
            _run_db(lambda db: otp_service.purge_phone_codes(db, phone))
            _await(_delete_phone_user(phone))

    def test_verify_creates_patient_account_but_links_nothing(self):
        phone = "09372223333"
        _await(_delete_phone_user(phone))
        try:
            body = self._request_code(phone=phone)
            verify = self._verify_code(phone, body["dev_otp"])
            self.assertEqual(verify.status_code, 200)

            async def _fetch_state():
                from sqlalchemy import select

                from app.models.patient import Patient

                async with SessionLocal() as db:
                    user = (
                        await db.execute(select(User).where(User.phone == phone))
                    ).scalar_one()
                    linked = (
                        await db.execute(select(Patient).where(Patient.user_id == user.id))
                    ).scalar_one_or_none()
                    records = (
                        await db.execute(select(Patient).where(Patient.phone == phone))
                    ).scalars().all()
                    return user, linked, records

            user, linked, records = _await(_fetch_state())
            self.assertEqual(user.role, "patient")
            self.assertIsNone(linked)
            self.assertEqual(records, [])
        finally:
            _await(_delete_phone_user(phone))
            _run_db(lambda db: otp_service.purge_phone_codes(db, phone))

    def test_only_hashes_are_persisted(self):
        body = self._request_code()
        code = body["dev_otp"]
        self.assertTrue(code)

        async def _fetch_hashes():
            from sqlalchemy import select

            from app.models.otp import OtpCode

            async with SessionLocal() as db:
                rows = (
                    await db.execute(
                        select(OtpCode).where(OtpCode.phone == self.phone)
                    )
                ).scalars().all()
                return [(row.code_hash, row.expires_at, row.attempts) for row in rows]

        hashes = _await(_fetch_hashes())
        self.assertTrue(hashes)
        for code_hash, _, _ in hashes:
            self.assertNotEqual(code_hash, code)
            self.assertEqual(len(code_hash), 64)

    def test_fake_provider_is_disabled_outside_dev_test(self):
        from app.auth import sms as sms_module

        with patch.dict(os.environ, {"APP_ENV": "production", "OTP_PROVIDER": "fake"}):
            self.assertFalse(sms_module.fake_provider_allowed())
            with self.assertRaises(AppError) as caught:
                sms_module.get_sms_provider()
            self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")
        with patch.dict(os.environ, {"OTP_PROVIDER": "totally-unknown"}):
            with self.assertRaises(AppError) as caught:
                sms_module.get_sms_provider()
            self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    def test_dev_response_marks_fake_channel(self):
        body = self._request_code()
        self.assertIn("DEVELOPMENT ONLY", body["dev_notice"])
        record = fake_sms.last_message(self.phone)
        self.assertIsNotNone(record)
        self.assertIn(body["dev_otp"], record)


if __name__ == "__main__":
    unittest.main()
