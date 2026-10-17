"""SMS delivery abstraction with a development-only fake provider.

Only the fake provider is implemented. Plugging a real SMS vendor only
requires a new class implementing ``SmsProvider`` plus configuration; see
README for the documented environment contract.
"""

from __future__ import annotations

import os
from typing import Protocol

from app.errors import AppError


def app_env() -> str:
    """Deployment environment name; unset means local development."""
    return os.getenv("APP_ENV", "development").strip().lower() or "development"


def provider_name() -> str:
    """Configured SMS provider name; only ``fake`` is implemented."""
    return os.getenv("OTP_PROVIDER", "fake").strip().lower() or "fake"


def fake_provider_allowed() -> bool:
    """The fake provider is only usable in development/test mode."""
    return app_env() in {"development", "test"} and provider_name() == "fake"


class SmsProvider(Protocol):
    def send(self, phone: str, body: str) -> None: ...


class FakeSmsProvider:
    """DEVELOPMENT/TEST ONLY. Keeps the last message per phone in memory."""

    def __init__(self) -> None:
        self.outbox: dict[str, str] = {}

    def send(self, phone: str, body: str) -> None:
        self.outbox[phone] = body

    def last_message(self, phone: str) -> str | None:
        return self.outbox.get(phone)


fake_sms = FakeSmsProvider()


def get_sms_provider() -> SmsProvider:
    """Resolve the configured SMS provider; fail safely when unavailable."""
    if provider_name() == "fake":
        if not fake_provider_allowed():
            raise AppError("COMMON_SERVICE_UNAVAILABLE")
        return fake_sms
    # No real vendor is implemented; refuse rather than silently dropping SMS.
    raise AppError("COMMON_SERVICE_UNAVAILABLE")
