"""Rate-limit regression tests for POST /auth/login (P1-1).

The limiter counts only FAILED attempts per target phone and per client IP
(sliding window), answers with COMMON_TOO_MANY_REQUESTS (429), and a
successful login forgives the account's past failures. Unknown phones are
counted exactly like existing ones so responses stay uniform.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["APP_ENV"] = "test"
os.environ["OTP_PROVIDER"] = "fake"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth.rate_limit import login_rate_limiter  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402

PASSWORD = "s3cret-pass"
STAFF_PHONE = "09121110001"
INACTIVE_PHONE = "09121110002"
UNKNOWN_PHONE = "09129999999"

ACCOUNT_LIMIT = {"LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "3"}
IP_LIMIT = {"LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "4"}
WIDE = {
    "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "100",
    "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
}


async def _seed_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    staff = User(
        id=400, full_name="staff", phone=STAFF_PHONE,
        password_hash=hash_password(PASSWORD), role="receptionist",
        is_active=True,
    )
    inactive = User(
        id=401, full_name="inactive", phone=INACTIVE_PHONE,
        password_hash=hash_password(PASSWORD), role="patient",
        is_active=False,
    )
    session.add_all([staff, inactive])
    await session.commit()
    return session_factory, engine


class _FakeClock:
    """Deterministic clock for window-expiry tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class LoginRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.session_factory, self.engine = await _seed_db()
        login_rate_limiter.reset()

        async def _override_get_db():
            async with self.session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = _override_get_db
        self.client = TestClient(app)

    async def asyncTearDown(self):
        login_rate_limiter.reset()
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()

    def _login(self, phone, password):
        return self.client.post(
            "/auth/login", json={"phone": phone, "password": password}
        )

    # --- Sequential failures reach the account limit ---

    async def test_sequential_failures_reach_limit_and_return_429(self):
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "3",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
            },
        ):
            for _ in range(3):
                response = self._login(STAFF_PHONE, "wrong-password")
                self.assertEqual(response.status_code, 401)
            blocked = self._login(STAFF_PHONE, "wrong-password")
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(
                blocked.json()["error"]["code"], "COMMON_TOO_MANY_REQUESTS"
            )

    # --- A success forgives the account's past failures ---

    async def test_success_resets_account_counter(self):
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "3",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
            },
        ):
            self.assertEqual(self._login(STAFF_PHONE, "wrong-1").status_code, 401)
            self.assertEqual(self._login(STAFF_PHONE, "wrong-2").status_code, 401)
            ok = self._login(STAFF_PHONE, PASSWORD)
            self.assertEqual(ok.status_code, 200)
            self.assertIn("access_token", ok.json())
            # After the success the account gets a fresh allowance.
            self.assertEqual(self._login(STAFF_PHONE, "wrong-3").status_code, 401)
            self.assertEqual(self._login(STAFF_PHONE, "wrong-4").status_code, 401)

    # --- Existing and unknown phones behave identically ---

    async def test_existing_and_unknown_phone_get_identical_responses(self):
        with patch.dict(os.environ, WIDE):
            existing = self._login(STAFF_PHONE, "wrong-password")
            unknown = self._login(UNKNOWN_PHONE, "whatever")
            self.assertEqual(existing.status_code, unknown.status_code)
            self.assertEqual(
                existing.json()["error"]["code"], unknown.json()["error"]["code"]
            )

    async def test_unknown_phone_is_rate_limited_like_existing(self):
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "2",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
            },
        ):
            self.assertEqual(self._login(UNKNOWN_PHONE, "x1").status_code, 401)
            self.assertEqual(self._login(UNKNOWN_PHONE, "x2").status_code, 401)
            blocked = self._login(UNKNOWN_PHONE, "x3")
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(
                blocked.json()["error"]["code"], "COMMON_TOO_MANY_REQUESTS"
            )

    # --- Window expiry restores access (no permanent lockout) ---

    async def test_window_expiry_allows_login_again(self):
        clock = _FakeClock()
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "2",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "100",
                "LOGIN_RATE_WINDOW_SECONDS": "10",
            },
        ):
            with patch("app.auth.rate_limit._monotonic", clock):
                with patch.object(login_rate_limiter, "_clock", clock):
                    self.assertEqual(self._login(STAFF_PHONE, "wrong-1").status_code, 401)
                    self.assertEqual(self._login(STAFF_PHONE, "wrong-2").status_code, 401)
                    self.assertEqual(self._login(STAFF_PHONE, "wrong-3").status_code, 429)
                    clock.advance(11.0)  # past the 10s window
                    ok = self._login(STAFF_PHONE, PASSWORD)
                    self.assertEqual(ok.status_code, 200)

    # --- Inactive accounts behave exactly like bad passwords ---

    async def test_inactive_account_uniform_and_rate_limited(self):
        with patch.dict(os.environ, WIDE):
            inactive = self._login(INACTIVE_PHONE, PASSWORD)
            unknown = self._login("09129999998", "whatever")
            self.assertEqual(inactive.status_code, unknown.status_code)
            self.assertEqual(
                inactive.json()["error"]["code"], unknown.json()["error"]["code"]
            )
            self.assertEqual(
                inactive.json()["error"]["message"],
                unknown.json()["error"]["message"],
            )
        login_rate_limiter.reset()
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "2",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
            },
        ):
            self.assertEqual(self._login(INACTIVE_PHONE, PASSWORD).status_code, 401)
            self.assertEqual(self._login(INACTIVE_PHONE, PASSWORD).status_code, 401)
            blocked = self._login(INACTIVE_PHONE, PASSWORD)
            self.assertEqual(blocked.status_code, 429)

    # --- IP limit protects across many accounts ---

    async def test_ip_limit_blocks_credential_stuffing_across_phones(self):
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "100",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "4",
            },
        ):
            for index in range(4):
                response = self._login(f"09120000{index:03d}", "wrong")
                self.assertEqual(response.status_code, 401)
            blocked = self._login("09120000999", "wrong")
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(
                blocked.json()["error"]["code"], "COMMON_TOO_MANY_REQUESTS"
            )

    # --- Concurrent access to the limiter is safe ---

    def test_concurrent_failures_settle_at_limit(self):
        # Directly hammer the shared limiter from many threads to prove the
        # in-memory store does not corrupt counts under concurrency. (The
        # HTTP path itself is single-threaded through the ASGI event loop,
        # so we exercise the store directly for a deterministic race test.)
        from app.auth.rate_limit import LoginRateLimiter

        limiter = LoginRateLimiter()
        limiter.check(ip="1.1.1.1", phone="09000000000")  # not limited yet

        def _one(_: int) -> None:
            limiter.record_failure(ip="1.1.1.1", phone="09000000000")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_one, range(8)))

        with self.assertRaises(Exception) as caught:
            limiter.check(ip="1.1.1.1", phone="09000000000")
        self.assertEqual(getattr(caught.exception, "code", None), "COMMON_TOO_MANY_REQUESTS")

    # --- OTP flow is independent of the login limiter ---

    async def test_login_limit_does_not_block_otp_endpoints(self):
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "2",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
            },
        ):
            self.assertEqual(self._login(STAFF_PHONE, "wrong-1").status_code, 401)
            self.assertEqual(self._login(STAFF_PHONE, "wrong-2").status_code, 401)
            self.assertEqual(self._login(STAFF_PHONE, "wrong-3").status_code, 429)
            otp = self.client.post(
                "/auth/otp/request", json={"phone": STAFF_PHONE}
            )
            self.assertEqual(otp.status_code, 202)

    # --- 429 bodies carry no sensitive data ---

    async def test_no_sensitive_data_in_429_response(self):
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "1",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "1000",
            },
        ):
            self._login(STAFF_PHONE, "wrong-password")
            blocked = self._login(STAFF_PHONE, "wrong-password")
            self.assertEqual(blocked.status_code, 429)
            self.assertNotIn("wrong-password", blocked.text)
            self.assertNotIn(STAFF_PHONE, blocked.text)

    # --- X-Forwarded-For is never trusted (P2 fix) ---

    async def test_forged_forwarded_header_cannot_change_ip_key(self):
        # The TestClient's transport host ("testclient") is the sole IP key.
        # A forged X-Forwarded-For must not move these failures onto another
        # (attacker-chosen) key, so the real key saturates and blocks.
        with patch.dict(
            os.environ,
            {
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_PHONE": "100",
                "LOGIN_RATE_FAILED_ATTEMPTS_PER_IP": "3",
            },
        ):
            forged = {"X-Forwarded-For": "203.0.113.7"}
            for index in range(3):
                response = self.client.post(
                    "/auth/login",
                    headers=forged,
                    json={"phone": f"09120000{index:03d}", "password": "wrong"},
                )
                self.assertEqual(response.status_code, 401)
            blocked = self.client.post(
                "/auth/login",
                headers=forged,
                json={"phone": "09120000999", "password": "wrong"},
            )
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(
                blocked.json()["error"]["code"], "COMMON_TOO_MANY_REQUESTS"
            )

    def test_client_ip_never_reads_forwarded_header(self):
        from starlette.datastructures import Address

        from app.auth.router import _client_ip

        # No transport client + forged header -> placeholder, header ignored.
        request = self._build_request(client=None, forwarded="203.0.113.7")
        self.assertEqual(_client_ip(request), "unknown")

        # Transport client present + forged header -> transport host wins.
        request = self._build_request(
            client=Address(host="198.51.100.9", port=1234),
            forwarded="203.0.113.7",
        )
        self.assertEqual(_client_ip(request), "198.51.100.9")

        # Transport client present but empty host -> placeholder, not header.
        request = self._build_request(
            client=Address(host="", port=1234), forwarded="203.0.113.7"
        )
        self.assertEqual(_client_ip(request), "unknown")

    @staticmethod
    def _build_request(client, forwarded: str):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/auth/login",
            "headers": [(b"x-forwarded-for", forwarded.encode())],
            "client": client,
        }
        return Request(scope)


if __name__ == "__main__":
    unittest.main()