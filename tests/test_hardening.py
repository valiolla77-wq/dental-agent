"""Tests for the abuse-protection and configuration hardening layer."""

import asyncio
import os
import unittest
from unittest.mock import patch

from app.auth.otp import sms_abuse_guard
from app.auth.rate_limit import ActionRateLimiter, LoginRateLimiter
from app.auth.security import hash_password, hash_password_async, verify_password_async
from app.errors import AppError
from app.startup_checks import collect_config_problems, validate_runtime_config

STRONG = "x" * 40
OTHER = "y" * 40


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ActionRateLimiterTests(unittest.TestCase):
    def test_blocks_after_limit_and_recovers_after_window(self):
        clock = _Clock()
        limiter = ActionRateLimiter(clock=clock)
        for _ in range(3):
            limiter.hit("chat", "1", limit=3, window=60)
        with self.assertRaises(AppError):
            limiter.hit("chat", "1", limit=3, window=60)
        clock.now += 61
        limiter.hit("chat", "1", limit=3, window=60)

    def test_buckets_and_users_are_independent(self):
        limiter = ActionRateLimiter(clock=_Clock())
        limiter.hit("chat", "1", limit=1, window=60)
        limiter.hit("feedback", "1", limit=1, window=60)
        limiter.hit("chat", "2", limit=1, window=60)
        with self.assertRaises(AppError):
            limiter.hit("chat", "1", limit=1, window=60)

    def test_expired_keys_are_collected(self):
        clock = _Clock()
        limiter = ActionRateLimiter(clock=clock)
        for index in range(50):
            limiter.hit("chat", str(index), limit=5, window=10)
        clock.now += 100
        limiter._collect_garbage(clock.now)
        self.assertEqual(len(limiter._hits), 0)


class LoginLimiterMemoryTests(unittest.TestCase):
    def test_checking_unknown_keys_does_not_grow_the_table(self):
        limiter = LoginRateLimiter(clock=_Clock())
        for index in range(500):
            limiter.check(ip=f"10.0.{index}.1", phone=f"0912{index:07d}")
        self.assertEqual(len(limiter._failures), 0)


class SmsAbuseGuardTests(unittest.TestCase):
    def setUp(self):
        sms_abuse_guard.reset()

    def tearDown(self):
        sms_abuse_guard.reset()

    def test_per_phone_daily_cap(self):
        with patch.dict(os.environ, {"OTP_PHONE_DAILY_LIMIT": "2"}):
            sms_abuse_guard.check_and_record("09120000000")
            sms_abuse_guard.check_and_record("09120000000")
            with self.assertRaises(AppError):
                sms_abuse_guard.check_and_record("09120000000")
            sms_abuse_guard.check_and_record("09120000001")

    def test_global_hourly_cap(self):
        with patch.dict(os.environ, {"OTP_GLOBAL_HOURLY_LIMIT": "2"}):
            sms_abuse_guard.check_and_record("09120000010")
            sms_abuse_guard.check_and_record("09120000011")
            with self.assertRaises(AppError):
                sms_abuse_guard.check_and_record("09120000012")


class StartupChecksTests(unittest.TestCase):
    def test_production_requires_strong_distinct_secrets(self):
        fatal, _ = collect_config_problems(
            {"APP_ENV": "production", "JWT_SECRET": "short"}
        )
        self.assertTrue(any("JWT_SECRET" in item for item in fatal))
        self.assertTrue(any("CONFIRMATION_HMAC_SECRET" in item for item in fatal))

        fatal, _ = collect_config_problems(
            {"APP_ENV": "production", "JWT_SECRET": STRONG, "CONFIRMATION_HMAC_SECRET": STRONG}
        )
        self.assertTrue(any("differ" in item for item in fatal))

    def test_unset_env_is_treated_as_production(self):
        fatal, _ = collect_config_problems({"JWT_SECRET": STRONG})
        self.assertTrue(fatal)

    def test_development_only_warns_but_missing_jwt_secret_is_always_fatal(self):
        fatal, warnings = collect_config_problems(
            {"APP_ENV": "development", "JWT_SECRET": "short"}
        )
        self.assertEqual(fatal, [])
        self.assertTrue(warnings)
        fatal, _ = collect_config_problems({"APP_ENV": "development"})
        self.assertTrue(any("JWT_SECRET is not set" in item for item in fatal))

    def test_valid_production_config_passes(self):
        validate_runtime_config(
            {
                "APP_ENV": "production",
                "JWT_SECRET": STRONG,
                "CONFIRMATION_HMAC_SECRET": OTHER,
                "OTP_PROVIDER": "smsir",
            }
        )

    def test_invalid_production_config_raises(self):
        with self.assertRaises(RuntimeError):
            validate_runtime_config({"APP_ENV": "production"})


class AsyncHashingTests(unittest.TestCase):
    def test_async_wrappers_match_sync_behaviour(self):
        async def scenario():
            hashed = await hash_password_async("correct-horse-1")
            self.assertTrue(await verify_password_async("correct-horse-1", hashed))
            self.assertFalse(await verify_password_async("nope-nope-1", hashed))
            self.assertFalse(await verify_password_async("x", "not-a-hash"))
            self.assertTrue(hashed.startswith("$argon2id$"))
            self.assertTrue(hash_password("a-b-c-d-e-1").startswith("$argon2id$"))

        asyncio.run(scenario())



class PersianDigitsTests(unittest.TestCase):
    def test_converts_latin_and_arabic_indic_digits(self):
        from app.utils.persian import to_persian_digits

        self.assertEqual(to_persian_digits("1405/08/06 ساعت 09:00"), "۱۴۰۵/۰۸/۰۶ ساعت ۰۹:۰۰")
        self.assertEqual(to_persian_digits("٠١٢"), "۰۱۲")
        self.assertEqual(to_persian_digits("بدون رقم"), "بدون رقم")
        self.assertEqual(to_persian_digits(12), "۱۲")


if __name__ == "__main__":
    unittest.main()
