"""Regression tests for the Bale messenger OTP channel.

Covers the phone→chat link lifecycle (contact-share only, 1:1), the
delivery provider (linked chat receives the code, unlinked phones fail
closed), the public channel descriptor and the poller's update handling.
All HTTP goes through injected fake transports/clients; no real network.
"""

import asyncio
import json
import os
import time
import unittest
from unittest.mock import patch

# Set test environment variables BEFORE importing app modules. The shared
# test database URL is read at import time by app.database.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["APP_ENV"] = "test"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.auth import bale as bale_module  # noqa: E402
from app.auth import otp as otp_service  # noqa: E402
from app.auth.bale import BaleBotClient, BaleProvider  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.main import app  # noqa: E402
from app.models.bale_link import BaleChatLink  # noqa: E402

BALE_ENV = {"OTP_PROVIDER": "bale", "BALE_BOT_TOKEN": "test-token"}


def _await(coro):
    return asyncio.run(coro)


def _run_db(coro_factory):
    async def _wrapper():
        async with SessionLocal() as db:
            return await coro_factory(db)

    return _await(_wrapper())


def _clear_all_links():
    async def _clear(db):
        await db.execute(delete(BaleChatLink))
        await db.commit()

    _run_db(_clear)


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Fake Bale API: records requests, always answers ``ok``."""

    def __init__(self, result: dict | None = None):
        self.requests: list[dict] = []
        self._result = result or {}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            payload = json.loads(request.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {}
        self.requests.append({"url": str(request.url), "payload": payload})
        return httpx.Response(200, json={"ok": True, "result": self._result})


class _FakeBot:
    """Poller double: records replies instead of calling Bale."""

    def __init__(self):
        self.sent: list[tuple[str, str, dict | None]] = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((str(chat_id), text, reply_markup))


class NormalizeMobileTests(unittest.TestCase):
    def test_accepts_common_iranian_formats(self):
        cases = {
            "09121112233": "09121112233",
            "+98 912 111 2233": "09121112233",
            "00989121112233": "09121112233",
            "989121112233": "09121112233",
            "9121112233": "09121112233",
        }
        for raw, expected in cases.items():
            self.assertEqual(bale_module.normalize_ir_mobile(raw), expected, raw)

    def test_rejects_non_mobile_input(self):
        for raw in ["", None, "12345", "0912111223", "091211122339", "abc"]:
            self.assertIsNone(bale_module.normalize_ir_mobile(raw), repr(raw))


class BaleProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _await(init_db())

    def setUp(self):
        _run_db(lambda db: bale_module.unlink_chat(db, "555"))
        _run_db(lambda db: bale_module.unlink_chat(db, "777"))

    def tearDown(self):
        bale_module.reset_runtime_state()

    def test_get_sms_provider_resolves_bale(self):
        with patch.dict(os.environ, BALE_ENV):
            provider = __import__("app.auth.sms", fromlist=["get_sms_provider"]).get_sms_provider()
            self.assertIsInstance(provider, BaleProvider)

    def test_provider_without_token_fails_closed(self):
        env = {"OTP_PROVIDER": "bale", "BALE_BOT_TOKEN": ""}
        with patch.dict(os.environ, env):
            from app.auth.sms import get_sms_provider

            with self.assertRaises(AppError) as ctx:
                get_sms_provider()
            self.assertEqual(ctx.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    def test_send_delivers_code_to_linked_chat(self):
        _run_db(lambda db: bale_module.link_phone(db, "09121110000", "555", "تست"))
        transport = _RecordingTransport()

        async def _send():
            provider = BaleProvider(client=BaleBotClient(token="test-token", transport=transport))
            await provider.send("09121110000", "کد ورود شما: 123456")

        _await(_send())
        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertIn("/bottest-token/sendMessage", request["url"])
        self.assertNotIn("test-token", json.dumps(request["payload"]))
        self.assertEqual(request["payload"]["chat_id"], "555")
        self.assertIn("123456", request["payload"]["text"])

    def test_send_finds_link_without_leading_zero(self):
        """A phone typed without the leading 0 still reaches the linked chat."""
        _run_db(lambda db: bale_module.link_phone(db, "09121110000", "555", None))
        transport = _RecordingTransport()

        async def _send():
            provider = BaleProvider(client=BaleBotClient(token="test-token", transport=transport))
            await provider.send("9121110000", "کد ورود شما: 123456")

        _await(_send())
        self.assertEqual(transport.requests[0]["payload"]["chat_id"], "555")

    def test_send_to_unlinked_phone_fails_closed(self):
        async def _send():
            provider = BaleProvider(
                client=BaleBotClient(token="test-token", transport=_RecordingTransport())
            )
            await provider.send("09330000000", "کد ورود شما: 123456")

        with self.assertRaises(AppError) as ctx:
            _await(_send())
        self.assertEqual(ctx.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    def test_request_otp_burns_code_when_phone_unlinked(self):
        """A synchronously-delivered OTP for an unlinked phone 503s and burns."""
        phone = "09330000001"
        with patch.dict(os.environ, BALE_ENV):

            async def _flow():
                async with SessionLocal() as db:
                    await otp_service.purge_phone_codes(db, phone)
                    with self.assertRaises(AppError) as ctx:
                        await otp_service.request_otp(db, phone, "test-ip")
                    self.assertEqual(ctx.exception.code, "COMMON_SERVICE_UNAVAILABLE")

                    from app.models.otp import OtpCode

                    rows = (
                        (await db.execute(select(OtpCode).where(OtpCode.phone == phone)))
                        .scalars()
                        .all()
                    )
                    self.assertTrue(rows)
                    self.assertTrue(all(row.consumed_at is not None for row in rows))
                    await otp_service.purge_phone_codes(db, phone)

            _await(_flow())


class LinkLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _await(init_db())

    def setUp(self):
        _clear_all_links()

    def tearDown(self):
        _clear_all_links()

    def test_link_phone_is_one_to_one_both_ways(self):
        async def _flow():
            async with SessionLocal() as db:
                self.assertTrue(await bale_module.link_phone(db, "09121110000", "555"))
                # Same chat, new phone: the chat's old row is replaced.
                self.assertTrue(await bale_module.link_phone(db, "09121110001", "555"))
                # Same phone, new chat: not a new phone, just a re-bind.
                self.assertFalse(await bale_module.link_phone(db, "09121110001", "777"))

                rows = (await db.execute(select(BaleChatLink))).scalars().all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].phone, "09121110001")
                self.assertEqual(rows[0].chat_id, "777")

        _await(_flow())

    def test_get_chat_id_for_phone_tolerates_format(self):
        async def _flow():
            async with SessionLocal() as db:
                await bale_module.link_phone(db, "09121110000", "555")
                self.assertEqual(await bale_module.get_chat_id_for_phone(db, "09121110000"), "555")
                self.assertEqual(
                    await bale_module.get_chat_id_for_phone(db, "+989121110000"), "555"
                )
                self.assertIsNone(await bale_module.get_chat_id_for_phone(db, "09330000000"))

        _await(_flow())


class PollerUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _await(init_db())

    def setUp(self):
        _clear_all_links()
        self.bot = _FakeBot()
        self.now = int(time.time())

    def tearDown(self):
        _clear_all_links()

    def _update(self, **message_extra):
        return {
            "update_id": 10,
            "message": {"chat": {"id": 777}, "date": self.now, **message_extra},
        }

    def test_start_sends_welcome_with_contact_keyboard(self):
        _await(bale_module.process_update(self._update(text="/start"), client=self.bot))
        self.assertEqual(len(self.bot.sent), 1)
        chat_id, text, markup = self.bot.sent[0]
        self.assertEqual(chat_id, "777")
        self.assertIn("یک‌بارمصرف", text)
        button = markup["keyboard"][0][0]
        self.assertTrue(button["request_contact"])

    def test_contact_share_links_chat_to_own_number(self):
        update = self._update(
            contact={"phone_number": "+989121112233", "first_name": "علی"},
            **{"from": {"first_name": "علی"}},
        )
        _await(bale_module.process_update(update, client=self.bot))

        async def _fetch():
            async with SessionLocal() as db:
                return await bale_module.get_chat_id_for_phone(db, "09121112233")

        self.assertEqual(_await(_fetch()), "777")
        chat_id, text, _ = self.bot.sent[0]
        self.assertEqual(chat_id, "777")
        self.assertIn("متصل شد", text)

    def test_typed_phone_is_never_linked(self):
        """Security: typing a number must not steal another chat's link."""

        async def _seed():
            async with SessionLocal() as db:
                await bale_module.link_phone(db, "09121112233", "777")

        _await(_seed())
        # A different chat types the victim's phone as plain text.
        update = {
            "update_id": 11,
            "message": {
                "chat": {"id": 888},
                "text": "09121112233",
                "date": self.now,
            },
        }
        _await(bale_module.process_update(update, client=self.bot))

        async def _fetch():
            async with SessionLocal() as db:
                return await bale_module.get_chat_id_for_phone(db, "09121112233")

        self.assertEqual(_await(_fetch()), "777")
        # The reply nudges towards the contact button and leaks no code.
        self.assertEqual(len(self.bot.sent), 1)
        self.assertIn("اشتراک شماره تماس", self.bot.sent[0][1])

    def test_invalid_contact_number_is_rejected(self):
        update = self._update(contact={"phone_number": "12345"})
        _await(bale_module.process_update(update, client=self.bot))
        self.assertIn("معتبر نیست", self.bot.sent[0][1])

        async def _count():
            async with SessionLocal() as db:
                rows = (await db.execute(select(BaleChatLink))).scalars().all()
                return len(rows)

        self.assertEqual(_await(_count()), 0)

    def test_unlink_removes_only_own_chat(self):
        async def _seed():
            async with SessionLocal() as db:
                await bale_module.link_phone(db, "09121112233", "777")

        _await(_seed())
        _await(bale_module.process_update(self._update(text="/unlink"), client=self.bot))

        async def _fetch():
            async with SessionLocal() as db:
                return await bale_module.get_chat_id_for_phone(db, "09121112233")

        self.assertIsNone(_await(_fetch()))
        self.assertIn("حذف شد", self.bot.sent[0][1])

    def test_non_message_update_is_ignored(self):
        _await(bale_module.process_update({"update_id": 12}, client=self.bot))
        self.assertEqual(self.bot.sent, [])


class ChannelEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _await(init_db())

    def setUp(self):
        bale_module.reset_runtime_state()
        self.client = TestClient(app)

    def tearDown(self):
        bale_module.reset_runtime_state()

    def test_bale_channel_exposes_public_bot_link(self):
        class _StubClient:
            async def get_me(self):
                return {"id": 1, "username": "@ClinikOtpBot"}

        env = dict(BALE_ENV)
        with patch.dict(os.environ, env), patch.object(bale_module, "BaleBotClient", _StubClient):
            response = self.client.get("/auth/otp/channel")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "bale")
        self.assertEqual(body["bot_username"], "ClinikOtpBot")
        self.assertEqual(body["bot_url"], "https://ble.ir/ClinikOtpBot")

    def test_bale_channel_without_token_has_no_link(self):
        env = {"OTP_PROVIDER": "bale", "BALE_BOT_TOKEN": ""}
        with patch.dict(os.environ, env):
            response = self.client.get("/auth/otp/channel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["provider"], "bale")
        self.assertIsNone(response.json()["bot_url"])

    def test_fake_channel_reports_provider_only(self):
        env = {"OTP_PROVIDER": "fake", "APP_ENV": "test"}
        with patch.dict(os.environ, env):
            response = self.client.get("/auth/otp/channel")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["provider"], "fake")
        self.assertIsNone(body["bot_username"])


if __name__ == "__main__":
    unittest.main()
