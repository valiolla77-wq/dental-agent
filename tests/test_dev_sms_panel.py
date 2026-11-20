"""Development-only local SMS panel: page, outbox, clear, and fail-closed gating."""

import asyncio
import os
import unittest
from unittest.mock import patch

# Test environment BEFORE app imports (app.database reads DATABASE_URL at import).
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.otp import _ip_requests  # noqa: E402
from app.auth.sms import fake_sms  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402


def _await(coro):
    """Run one coroutine on a fresh loop (sync unittest context)."""
    return asyncio.run(coro)


class DevSmsPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _await(init_db())

    def setUp(self):
        fake_sms.clear()
        _ip_requests.clear()
        self.client = TestClient(app)

    def tearDown(self):
        fake_sms.clear()

    def test_panel_page_is_served_with_disclaimer(self):
        response = self.client.get("/dev/sms")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        for marker in (
            "سامانه پیامک لوکال",
            "شبیه‌سازی‌شده",
            "/dev/sms/outbox.json",
            "پاک‌کردن اینباکس",
        ):
            self.assertIn(marker, response.text)

    def test_outbox_lists_delivered_otp_message(self):
        phone = "09370001234"
        request = self.client.post("/auth/otp/request", json={"phone": phone})
        self.assertEqual(request.status_code, 202)
        code = request.json()["dev_otp"]
        self.assertTrue(code)

        outbox = self.client.get("/dev/sms/outbox.json")
        self.assertEqual(outbox.status_code, 200)
        messages = outbox.json()["messages"]
        matched = [m for m in messages if m["phone"] == phone]
        self.assertEqual(len(matched), 1)
        self.assertIn(code, matched[0]["body"])

    def test_clear_empties_the_inbox(self):
        self.client.post("/auth/otp/request", json={"phone": "09370001235"})
        cleared = self.client.post("/dev/sms/clear")
        self.assertEqual(cleared.status_code, 200)
        self.assertTrue(cleared.json()["cleared"])
        self.assertEqual(self.client.get("/dev/sms/outbox.json").json()["messages"], [])

    def test_age_seconds_are_reported(self):
        self.client.post("/auth/otp/request", json={"phone": "09370001236"})
        message = self.client.get("/dev/sms/outbox.json").json()["messages"][0]
        self.assertGreaterEqual(message["age_seconds"], 0)
        self.assertLess(message["age_seconds"], 60)

    def test_panel_is_locked_when_real_provider_is_selected(self):
        with patch.dict(os.environ, {"OTP_PROVIDER": "smsir"}):
            self.assertEqual(self.client.get("/dev/sms").status_code, 404)
            self.assertEqual(self.client.get("/dev/sms/outbox.json").status_code, 404)
            # No message sneaks into the outbox even if an OTP was requested.
            self.client.post("/auth/otp/request", json={"phone": "09370001237"})
            self.assertEqual(
                self.client.get("/dev/sms/outbox.json", follow_redirects=False).status_code,
                404,
            )
            self.assertEqual(self.client.post("/dev/sms/clear").status_code, 404)

    def test_panel_is_locked_in_production_even_with_fake_provider(self):
        with patch.dict(
            os.environ, {"APP_ENV": "production", "OTP_PROVIDER": "fake"}
        ):
            self.assertEqual(self.client.get("/dev/sms").status_code, 404)
            self.assertEqual(self.client.get("/dev/sms/outbox.json").status_code, 404)
            self.assertEqual(self.client.post("/dev/sms/clear").status_code, 404)


if __name__ == "__main__":
    unittest.main()
