"""Sliding-window limiter over FAILED password logins (P1-1).

Design notes:
- Two independent keys per attempt: the client IP and the *target* phone.
  A distributed attacker needs many IPs to brute-force one account, while
  a single noisy IP cannot quietly probe unlimited accounts.
- Only failed attempts are counted, and a successful login forgives the
  account's past failures; windows expire on their own, so a victim can
  never be locked out permanently by an attacker.
- Unknown phones are counted exactly like existing ones, so throttling
  behaviour cannot be used to enumerate accounts or infer account state.
- In-memory and single process: with multiple uvicorn workers each process
  keeps its own counters (limits apply per worker). Swap this class for a
  shared store (e.g. Redis) without changing the call sites in the login
  route. No passwords, tokens, or phone numbers are ever logged here.
"""

from __future__ import annotations

import os
import time
from collections import deque
from collections.abc import Callable

from app.errors import AppError


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _failed_attempts_per_phone() -> int:
    return _env_int("LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE", 5)


def _failed_attempts_per_ip() -> int:
    return _env_int("LOGIN_RATE_FAILED_ATTEMPTS_PER_IP", 20)


def _window_seconds() -> int:
    return _env_int("LOGIN_RATE_WINDOW_SECONDS", 900, minimum=1)


def _monotonic() -> float:
    """Clock indirection so window-expiry tests can patch time deterministically."""
    return time.monotonic()


class LoginRateLimiter:
    """Sliding-window counters over failed login attempts (single process)."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or _monotonic
        # key -> monotonic timestamps of recent failed attempts
        self._failures: dict[str, deque[float]] = {}

    @staticmethod
    def _phone_key(phone: str) -> str:
        return f"phone:{phone.strip()}"

    @staticmethod
    def _ip_key(ip: str) -> str:
        return f"ip:{ip}"

    def _pruned(self, key: str, window: float) -> deque[float]:
        now = self._clock()
        history = self._failures.setdefault(key, deque())
        while history and now - history[0] >= window:
            history.popleft()
        return history

    def check(self, *, ip: str, phone: str) -> None:
        """Raise COMMON_TOO_MANY_REQUESTS when either key is saturated."""
        window = float(_window_seconds())
        limits = (
            (self._phone_key(phone), _failed_attempts_per_phone()),
            (self._ip_key(ip), _failed_attempts_per_ip()),
        )
        for key, limit in limits:
            history = self._pruned(key, window)
            if len(history) >= limit:
                raise AppError("COMMON_TOO_MANY_REQUESTS")

    def record_failure(self, *, ip: str, phone: str) -> None:
        now = self._clock()
        window = float(_window_seconds())
        for key in (self._phone_key(phone), self._ip_key(ip)):
            self._pruned(key, window).append(now)

    def record_success(self, *, phone: str) -> None:
        """A successful login forgives the account's past failures.

        The IP counter intentionally keeps its history: an attacker cannot
        reset the IP limit by logging into one of their own accounts.
        """
        self._failures.pop(self._phone_key(phone), None)

    def reset(self) -> None:
        """Testing helper: clear all counters."""
        self._failures.clear()


login_rate_limiter = LoginRateLimiter()