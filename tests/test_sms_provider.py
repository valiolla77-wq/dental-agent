"""Unit tests for the SMS.ir provider (no real network calls).

A fake ``httpx`` transport captures the outgoing request so we can verify the
wire contract, and every failure path must surface only the generic
``COMMON_SERVICE_UNAVAILABLE`` code without leaking the API key or OTP code.
"""

import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.auth.sms import SmsIrProvider, fake_provider_allowed, get_sms_provider
from app.errors import AppError

API_KEY = "test-api-key-not-real"
CODE = "654321"


def _transport(status_code=200, payload=None, captured=None):
    """Return a mock transport that records requests and returns a response."""

    def handler(request):
        if captured is not None:
            captured.append(request)
        body = payload if payload is not None else {"status": 1, "message": "ok"}
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler)


def _forbidden_transport():
    """Transport that fails the test if the provider calls the network."""

    def handler(request):
        raise AssertionError("provider must not call the network here")

    return httpx.MockTransport(handler)


def _body(request):
    return json.loads(request.content.decode("utf-8"))


class SmsProviderSelectionTests(unittest.TestCase):
    def test_smsir_is_selected_from_environment(self):
        with patch.dict(os.environ, {"OTP_PROVIDER": "smsir"}):
            provider = get_sms_provider()
            self.assertIsInstance(provider, SmsIrProvider)

    def test_smsir_never_enables_dev_otp(self):
        with patch.dict(
            os.environ, {"OTP_PROVIDER": "smsir", "APP_ENV": "development"}
        ):
            self.assertFalse(fake_provider_allowed())

    def test_unknown_provider_still_fails_closed(self):
        with patch.dict(os.environ, {"OTP_PROVIDER": "another-vendor"}):
            with self.assertRaises(AppError) as caught:
                get_sms_provider()
            self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")


class SmsIrTemplateModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_verify_template_payload(self):
        captured = []
        provider = SmsIrProvider(
            api_key=API_KEY,
            template_id="123456",
            template_parameter="CODE",
            transport=_transport(captured=captured),
        )

        await provider.send("09121234567", "ignored body", code=CODE)

        self.assertEqual(len(captured), 1)
        request = captured[0]
        self.assertEqual(str(request.url), "https://api.sms.ir/v1/send/verify")
        self.assertEqual(request.headers["x-api-key"], API_KEY)
        self.assertEqual(
            _body(request),
            {
                "mobile": "9121234567",
                "templateId": 123456,
                "parameters": [{"name": "CODE", "value": CODE}],
            },
        )

    async def test_template_mode_requires_a_code(self):
        captured = []
        provider = SmsIrProvider(
            api_key=API_KEY,
            template_id=123456,
            transport=_forbidden_transport(),
        )
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "no code here")
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")
        self.assertEqual(captured, [])

    async def test_template_mode_rejects_bad_template_id(self):
        provider = SmsIrProvider(
            api_key=API_KEY,
            template_id="not-a-number",
            transport=_forbidden_transport(),
        )
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")


class SmsIrLineModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bulk_payload_uses_service_line(self):
        captured = []
        provider = SmsIrProvider(
            api_key=API_KEY,
            line_number="30004505000017",
            transport=_transport(captured=captured),
        )

        await provider.send("09121234567", f"کد ورود شما: {CODE}", code=CODE)

        request = captured[0]
        self.assertEqual(str(request.url), "https://api.sms.ir/v1/send/bulk")
        self.assertEqual(
            _body(request),
            {
                "lineNumber": 30004505000017,
                "messageText": f"کد ورود شما: {CODE}",
                "mobiles": ["09121234567"],
            },
        )

    async def test_phone_formats_are_normalized(self):
        for raw in ("09121234567", "9121234567", "+989121234567", "00989121234567"):
            captured = []
            provider = SmsIrProvider(
                api_key=API_KEY,
                line_number="30004505000017",
                transport=_transport(captured=captured),
            )
            await provider.send(raw, "body", code=CODE)
            self.assertEqual(_body(captured[0])["mobiles"], ["09121234567"])


class SmsIrFailureTests(unittest.IsolatedAsyncioTestCase):
    def _provider(self, **kwargs):
        defaults = {
            "api_key": API_KEY,
            "template_id": 123456,
            "transport": _forbidden_transport(),
        }
        defaults.update(kwargs)
        return SmsIrProvider(**defaults)

    async def test_missing_api_key_fails_closed(self):
        with self.assertRaises(AppError) as caught:
            await self._provider(api_key="").send(
                "09121234567", "body", code=CODE
            )
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")
        self.assertNotIn(API_KEY, str(caught.exception))

    async def test_missing_channel_configuration_fails_closed(self):
        provider = SmsIrProvider(
            api_key=API_KEY,
            line_number="",
            template_id="",
            transport=_forbidden_transport(),
        )
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    async def test_invalid_mobile_fails_closed_without_calling_vendor(self):
        with self.assertRaises(AppError) as caught:
            await self._provider().send("not-a-phone", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    async def test_api_level_failure_is_generic(self):
        provider = self._provider(
            transport=_transport(payload={"status": 0, "message": "invalid key"})
        )
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")
        self.assertNotIn("invalid key", str(caught.exception))

    async def test_http_error_status_is_generic(self):
        provider = self._provider(
            transport=_transport(status_code=401, payload={"status": 0})
        )
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    async def test_malformed_response_is_generic(self):
        provider = self._provider(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"<html>oops</html>")
            )
        )
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")

    async def test_network_error_is_generic(self):
        def handler(request):
            raise httpx.ConnectTimeout("timed out")

        provider = self._provider(transport=httpx.MockTransport(handler))
        with self.assertRaises(AppError) as caught:
            await provider.send("09121234567", "body", code=CODE)
        self.assertEqual(caught.exception.code, "COMMON_SERVICE_UNAVAILABLE")
        self.assertNotIn(CODE, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
