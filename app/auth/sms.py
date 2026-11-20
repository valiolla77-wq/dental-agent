"""SMS delivery abstraction with development and real-provider implementations.

Providers:
- ``fake`` (default, development/test only): local SMS simulator. Messages are
  kept in memory and surfaced by the development-only panel at ``/dev/sms``.
  ``dev_otp`` is only exposed when this provider is active and ``APP_ENV`` is
  explicitly ``development``/``test``.
- ``smsir``: real delivery through the SMS.ir REST API v1
  (https://sms.ir/rest-api/). Credentials are read from the environment only.
- ``bale``: delivery through the clinic's Bale messenger bot to the chat the
  patient linked via ``request_contact`` (see ``app/auth/bale.py``). No SMS
  credit is consumed; the phone→chat mapping lives in ``bale_chat_links``.

The smsir provider supports two delivery modes, chosen by configuration:
- Verification-template mode (preferred for OTP): ``SMSIR_VERIFY_TEMPLATE_ID``
  is set, so the panel template (e.g. ``کد تایید شما: #CODE#``) is rendered by
  SMS.ir and the code is passed as a named parameter.
- Service-line mode: ``SMSIR_LINE_NUMBER`` is set and the plain message body
  is sent through ``/v1/send/bulk``.

Security notes:
- The API key, bot token and OTP codes are never logged, persisted, or
  included in raised errors; callers only see the generic
  ``COMMON_SERVICE_UNAVAILABLE``.
- Failures are fail-closed. Every provider uses a finite timeout and fully
  async I/O, so a slow vendor can never block the event loop.
"""

from __future__ import annotations

import os
import re
import time
from typing import Protocol

import httpx

from app.errors import AppError

SMSIR_BASE_URL = "https://api.sms.ir"
SMSIR_TIMEOUT_SECONDS = 10.0

_GENERIC_FAILURE = "COMMON_SERVICE_UNAVAILABLE"


def app_env() -> str:
    """Deployment environment name; only an explicit value is honored.

    Fail-safe: unset or blank APP_ENV is treated as production so that
    development-only helpers (the fake SMS provider) are never enabled by
    accident. Local development must opt in with APP_ENV=development.
    """
    return os.getenv("APP_ENV", "production").strip().lower() or "production"


def provider_name() -> str:
    """Configured delivery provider name: ``fake``, ``smsir`` or ``bale``."""
    return os.getenv("OTP_PROVIDER", "fake").strip().lower() or "fake"


def fake_provider_allowed() -> bool:
    """The fake provider is only usable in development/test mode."""
    return app_env() in {"development", "test"} and provider_name() == "fake"


class SmsProvider(Protocol):
    async def send(self, phone: str, body: str, code: str | None = None) -> None:
        """Deliver an OTP message. ``code`` is used by template-mode vendors."""
        ...


class FakeSmsProvider:
    """DEVELOPMENT/TEST ONLY. Local SMS simulator with a visible backlog.

    Keeps the last message per phone (for tests) plus a small append-only log
    that the development SMS panel (``/dev/sms``) serves as a simulated inbox.
    """

    _LOG_LIMIT = 200

    def __init__(self) -> None:
        self.outbox: dict[str, str] = {}
        self._sent_log: list[dict[str, float | str]] = []

    async def send(self, phone: str, body: str, code: str | None = None) -> None:
        self.outbox[phone] = body
        self._sent_log.append({"phone": phone, "body": body, "at": time.time()})
        del self._sent_log[: -self._LOG_LIMIT]

    def sent_messages(self) -> list[dict[str, float | str]]:
        return list(self._sent_log)

    def clear(self) -> None:
        self.outbox.clear()
        del self._sent_log[:]

    def last_message(self, phone: str) -> str | None:
        return self.outbox.get(phone)


fake_sms = FakeSmsProvider()


def _normalize_mobile(phone: str) -> str:
    """Return the 10-digit national mobile number used by SMS.ir examples.

    Accepts ``0912...``, ``912...``, ``+98912...`` and ``0098912...``.
    Raises the generic error for anything that cannot be a mobile number.
    """
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("0098"):
        digits = digits[4:]
    elif digits.startswith("98") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10 or not digits.startswith("9"):
        raise AppError(_GENERIC_FAILURE)
    return digits


class SmsIrProvider:
    """SMS.ir REST API v1 delivery.

    Constructor arguments default to the environment. Tests may inject all
    values plus an ``httpx`` transport, so no real network call is ever made
    by the test suite.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        line_number: str | None = None,
        template_id: str | int | None = None,
        template_parameter: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.getenv("SMSIR_API_KEY", "")
        ).strip()
        self._line_number = (
            line_number
            if line_number is not None
            else os.getenv("SMSIR_LINE_NUMBER", "")
        ).strip()
        self._template_id = (
            str(template_id)
            if template_id is not None
            else os.getenv("SMSIR_VERIFY_TEMPLATE_ID", "")
        ).strip()
        self._template_parameter = (
            template_parameter
            if template_parameter is not None
            else os.getenv("SMSIR_VERIFY_PARAMETER", "CODE")
        ).strip() or "CODE"
        self._transport = transport

    async def send(self, phone: str, body: str, code: str | None = None) -> None:
        """Send one message; raise the generic unavailable error on any issue."""
        if not self._api_key:
            raise AppError(_GENERIC_FAILURE)

        mobile = _normalize_mobile(phone)
        if self._template_id:
            # Template mode: the panel owns the wording; only the code travels.
            template_id = self._positive_int(self._template_id)
            if not code:
                raise AppError(_GENERIC_FAILURE)
            url = f"{SMSIR_BASE_URL}/v1/send/verify"
            payload = {
                "mobile": mobile,
                "templateId": template_id,
                "parameters": [
                    {"name": self._template_parameter, "value": code},
                ],
            }
        elif self._line_number:
            url = f"{SMSIR_BASE_URL}/v1/send/bulk"
            line_number: str | int = self._line_number
            if self._line_number.isdigit():
                line_number = int(self._line_number)
            payload = {
                "lineNumber": line_number,
                "messageText": body,
                "mobiles": [f"0{mobile}"],
            }
        else:
            # No template and no service line: refuse instead of silently
            # pretending the code was delivered.
            raise AppError(_GENERIC_FAILURE)

        headers = {
            "X-API-KEY": self._api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(SMSIR_TIMEOUT_SECONDS),
                transport=self._transport,
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError:
            raise AppError(_GENERIC_FAILURE) from None

        try:
            data = response.json()
        except ValueError:
            raise AppError(_GENERIC_FAILURE) from None
        if (
            response.status_code != 200
            or not isinstance(data, dict)
            or data.get("status") != 1
        ):
            raise AppError(_GENERIC_FAILURE)

    @staticmethod
    def _positive_int(raw: str) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise AppError(_GENERIC_FAILURE) from None
        if value <= 0:
            raise AppError(_GENERIC_FAILURE)
        return value


def get_sms_provider() -> SmsProvider:
    """Resolve the configured delivery provider; fail safely when unavailable."""
    name = provider_name()
    if name == "fake":
        if not fake_provider_allowed():
            raise AppError(_GENERIC_FAILURE)
        return fake_sms
    if name == "smsir":
        return SmsIrProvider()
    if name == "bale":
        # Imported lazily: the Bale module reads ``provider_name`` back from
        # here, so a module-level import would be circular.
        from app.auth.bale import BaleProvider

        return BaleProvider()
    # Unknown vendor: refuse rather than silently dropping the code.
    raise AppError(_GENERIC_FAILURE)
