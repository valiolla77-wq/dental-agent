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

    # Hard bound on tracked keys: attacker-chosen phones/IPs must never be able
    # to grow this table without limit.
    _MAX_KEYS = 10_000

    def _pruned(self, key: str, window: float, *, create: bool = False) -> deque[float]:
        now = self._clock()
        history = self._failures.get(key)
        if history is None:
            if not create:
                return deque()
            history = self._failures[key] = deque()
        while history and now - history[0] >= window:
            history.popleft()
        if not history and not create:
            self._failures.pop(key, None)
        return history

    def _collect_garbage(self, window: float) -> None:
        if len(self._failures) <= self._MAX_KEYS:
            return
        now = self._clock()
        stale = [
            key
            for key, history in self._failures.items()
            if not history or now - history[-1] >= window
        ]
        for key in stale:
            del self._failures[key]

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
            self._pruned(key, window, create=True).append(now)
        self._collect_garbage(window)

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


class ActionRateLimiter:
    """Per-key sliding-window limiter for authenticated actions (chat, feedback).

    Single process and in memory, like the login limiter; swap for a shared
    store when running several workers. Buckets are independent, so chat
    traffic never consumes the feedback allowance.
    """

    _MAX_KEYS = 10_000
    _GC_EVERY = 256

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or _monotonic
        # (bucket, key) -> (window seconds, monotonic hit timestamps)
        self._hits: dict[tuple[str, str], tuple[float, deque[float]]] = {}
        self._calls = 0

    def hit(self, bucket: str, key: str, *, limit: int, window: float) -> None:
        """Record one action or raise COMMON_TOO_MANY_REQUESTS when saturated."""
        now = self._clock()
        self._calls += 1
        if self._calls % self._GC_EVERY == 0 or len(self._hits) > self._MAX_KEYS:
            self._collect_garbage(now)
        _, history = self._hits.setdefault((bucket, key), (window, deque()))
        while history and now - history[0] >= window:
            history.popleft()
        if len(history) >= limit:
            raise AppError("COMMON_TOO_MANY_REQUESTS")
        history.append(now)
        self._hits[(bucket, key)] = (window, history)

    def _collect_garbage(self, now: float) -> None:
        stale = [
            key
            for key, (window, history) in self._hits.items()
            if not history or now - history[-1] >= window
        ]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


action_rate_limiter = ActionRateLimiter()