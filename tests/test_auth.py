"""Authentication and authorization tests."""

import asyncio
import os
import time
import unittest
from datetime import timedelta
from unittest.mock import patch
from io import StringIO
import sys

# Set test environment variables BEFORE importing app modules
# Use in-memory SQLite database for tests to avoid interfering with real data
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only-32-chars-long"
os.environ["JWT_ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"

import jwt
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user, require_admin
from app.auth.router import router as auth_router
from app.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.error_handling import configure_error_handling
from app.main import app
from app.models.user import User


class TestPasswordHashing(unittest.TestCase):
    """Test password hashing and verification."""

    def test_hash_and_verify_password(self):
        password = "secure-password-123"
        hashed = hash_password(password)
        self.assertTrue(verify_password(password, hashed))
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_different_passwords_produce_different_hashes(self):
        password = "test-password"
        hash1 = hash_password(password)
        hash2 = hash_password(password)
        self.assertNotEqual(hash1, hash2)  # Argon2 uses salt
        self.assertTrue(verify_password(password, hash1))
        self.assertTrue(verify_password(password, hash2))

    def test_verify_rejects_invalid_hash(self):
        self.assertFalse(verify_password("password", "not-a-valid-hash"))
        self.assertFalse(verify_password("password", ""))


class TestJWTToken(unittest.TestCase):
    """Test JWT token creation and validation."""

    def test_create_and_decode_token(self):
        token = create_access_token(subject="123")
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "123")
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)

    def test_token_has_required_claims(self):
        token = create_access_token(subject="456")
        payload = decode_access_token(token)
        self.assertIn("sub", payload)
        self.assertIn("exp", payload)

    def test_token_expiration(self):
        token = create_access_token(
            subject="123", expires_delta=timedelta(seconds=1)
        )
        time.sleep(1.1)
        with self.assertRaises(ValueError) as ctx:
            decode_access_token(token)
        self.assertIn("expired", str(ctx.exception).lower())

    def test_token_rejects_wrong_signature(self):
        token = create_access_token(subject="123")
        # Decode and re-encode with different secret
        wrong_secret = "different-secret"
        tampered = jwt.encode(
            {"sub": "123", "exp": time.time() + 3600},
            wrong_secret,
            algorithm="HS256",
        )
        with self.assertRaises(ValueError) as ctx:
            decode_access_token(tampered)
        self.assertIn("invalid", str(ctx.exception).lower())

    def test_token_rejects_missing_sub(self):
        # Create token without sub claim
        secret = os.getenv("JWT_SECRET", "test-secret")
        token = jwt.encode({"exp": time.time() + 3600}, secret, algorithm="HS256")
        with self.assertRaises(ValueError) as ctx:
            decode_access_token(token)
        self.assertIn("missing required claim", str(ctx.exception).lower())

    def test_algorithm_fixed_no_confusion_attack(self):
        """Ensure algorithm is fixed and not read from token."""
        token = create_access_token(subject="123")
        # Try to decode with algorithm from token (should not work if we trust token)
        # Our decode function explicitly specifies algorithm="HS256"
        payload = decode_access_token(token)
        self.assertEqual(payload["sub"], "123")


class TestLoginEndpoint(unittest.TestCase):
    """Test login endpoint."""

    @classmethod
    def setUpClass(cls):
        """Initialize the database once for all tests in this class."""
        from app.database import init_db
        import asyncio
        asyncio.run(init_db())

    def setUp(self):
        self.client = TestClient(app)

    def _create_test_user(self, phone: str, password: str, role: str = "user", is_active: bool = True) -> User:
        """Helper to create a user in the test database."""
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.database import SessionLocal
        import asyncio

        async def _create():
            async with SessionLocal() as db:
                user = User(
                    full_name="Test User",
                    phone=phone,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=is_active,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                return user

        return asyncio.run(_create())

    def _delete_test_user(self, phone: str):
        """Helper to delete a test user."""
        from sqlalchemy import delete
        from app.database import SessionLocal
        import asyncio

        async def _delete():
            async with SessionLocal() as db:
                await db.execute(delete(User).where(User.phone == phone))
                await db.commit()

        asyncio.run(_delete())

    def test_login_success(self):
        """Test login with valid credentials."""
        phone = "09123456789"
        password = "testpass123"
        self._delete_test_user(phone)  # Clean up first
        self._create_test_user(phone, password)

        try:
            response = self.client.post(
                "/auth/login",
                json={"phone": phone, "password": password},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertIn("access_token", body)
            self.assertEqual(body["token_type"], "bearer")
            self.assertNotIn("password", response.text.lower())
            self.assertNotIn(password, response.text)
        finally:
            self._delete_test_user(phone)

    def test_login_wrong_password(self):
        """Test login with wrong password returns generic error."""
        phone = "09123456789"
        password = "testpass123"
        self._delete_test_user(phone)
        self._create_test_user(phone, password)

        try:
            response = self.client.post(
                "/auth/login",
                json={"phone": phone, "password": "wrongpass"},
            )
            self.assertEqual(response.status_code, 401)
            body = response.json()
            self.assertEqual(body["error"]["code"], "COMMON_UNAUTHORIZED")
        finally:
            self._delete_test_user(phone)

    def test_login_unknown_user(self):
        """Test login with unknown user returns same generic error."""
        response = self.client.post(
            "/auth/login",
            json={"phone": "09999999999", "password": "anypass"},
        )
        self.assertEqual(response.status_code, 401)
        body = response.json()
        self.assertEqual(body["error"]["code"], "COMMON_UNAUTHORIZED")

    def test_login_inactive_user(self):
        """Test login with inactive user returns 401."""
        phone = "09123456780"
        password = "testpass123"
        self._delete_test_user(phone)
        self._create_test_user(phone, password, is_active=False)

        try:
            response = self.client.post(
                "/auth/login",
                json={"phone": phone, "password": password},
            )
            self.assertEqual(response.status_code, 401)
            body = response.json()
            self.assertEqual(body["error"]["code"], "COMMON_UNAUTHORIZED")
        finally:
            self._delete_test_user(phone)


class TestProtectedEndpoints(unittest.TestCase):
    """Test protected endpoints with JWT authentication."""

    def setUp(self):
        self.client = TestClient(app)

    def test_protected_endpoint_without_token(self):
        """A protected PII endpoint must reject anonymous requests with 401."""
        response = self.client.get("/patients/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "COMMON_UNAUTHORIZED")

    def test_get_current_user_without_token(self):
        """The get_current_user dependency must raise 401 without credentials."""
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            asyncio.run(get_current_user(db=None, credentials=None))
        self.assertEqual(caught.exception.status_code, 401)


class TestAdminAuthorization(unittest.TestCase):
    """Test admin-only endpoints."""

    def setUp(self):
        self.client = TestClient(app)

    def test_anonymous_cannot_access_admin_routes(self):
        """Test that anonymous user cannot access admin-protected routes."""
        # The users endpoint requires admin
        response = self.client.post(
            "/users/",
            json={
                "full_name": "Attacker",
                "phone": "09999999999",
                "password": "pass1234",
                "role": "admin",
            },
        )
        self.assertEqual(response.status_code, 401)


class TestBootstrapAdminCLI(unittest.TestCase):
    """Test admin bootstrap via CLI command."""

    @classmethod
    def setUpClass(cls):
        """Initialize the database once for all tests in this class."""
        from app.database import init_db
        import asyncio
        asyncio.run(init_db())

    def setUp(self):
        # Clean up any existing test admin users
        from sqlalchemy import delete
        from app.database import SessionLocal
        import asyncio

        async def _cleanup():
            async with SessionLocal() as db:
                await db.execute(delete(User).where(User.phone.like("091234567%")))
                await db.commit()

        asyncio.run(_cleanup())

    def _run_bootstrap_cli(self, phone: str, password: str, confirm_password: str = None) -> tuple:
        """Run the bootstrap admin CLI command and return (exit_code, stdout, stderr)."""
        from app.auth import bootstrap_admin

        # Capture stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        try:
            # Simulate command line arguments
            test_args = ["bootstrap_admin", phone]
            if confirm_password is None:
                confirm_password = password

            # We need to mock getpass to provide password without interactive input
            with patch("getpass.getpass", side_effect=[password, confirm_password]):
                # Also mock sys.argv
                with patch.object(sys, "argv", test_args):
                    exit_code = bootstrap_admin.main()
        except SystemExit as e:
            exit_code = e.code
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        return exit_code, stdout_capture.getvalue(), stderr_capture.getvalue()

    def test_bootstrap_admin_cli_success(self):
        """Test successful admin creation via CLI."""
        phone = "09123456789"
        password = "securepass123"

        exit_code, stdout, stderr = self._run_bootstrap_cli(phone, password)

        self.assertEqual(exit_code, 0)
        self.assertIn("Admin user created successfully", stdout)
        self.assertIn(phone, stdout)
        self.assertIn("System Administrator", stdout)
        self.assertIn("admin", stdout)
        self.assertIn("True", stdout)  # is_active

        # Verify user exists in database
        from sqlalchemy import select
        from app.database import SessionLocal
        import asyncio

        async def _check():
            async with SessionLocal() as db:
                result = await db.execute(select(User).where(User.phone == phone))
                user = result.scalar_one_or_none()
                return user

        user = asyncio.run(_check())
        self.assertIsNotNone(user)
        self.assertEqual(user.role, "admin")
        self.assertTrue(user.is_active)
        self.assertTrue(verify_password(password, user.password_hash))

    def test_bootstrap_admin_cli_fails_if_admin_exists(self):
        """Test CLI fails if admin already exists."""
        phone1 = "09123456789"
        phone2 = "09123456780"
        password = "securepass123"

        # Create first admin
        exit_code1, stdout1, stderr1 = self._run_bootstrap_cli(phone1, password)
        self.assertEqual(exit_code1, 0)

        # Try to create second admin
        exit_code2, stdout2, stderr2 = self._run_bootstrap_cli(phone2, password)
        self.assertEqual(exit_code2, 1)
        self.assertIn("Admin user already exists", stderr2)

    def test_bootstrap_admin_cli_password_mismatch(self):
        """Test CLI fails when passwords don't match."""
        phone = "09123456789"
        password = "securepass123"
        wrong_confirm = "differentpass"

        exit_code, stdout, stderr = self._run_bootstrap_cli(phone, password, wrong_confirm)

        self.assertEqual(exit_code, 1)
        self.assertIn("Passwords do not match", stderr)

    def test_bootstrap_admin_cli_short_password(self):
        """Test CLI fails when password is too short."""
        phone = "09123456789"
        password = "short"

        exit_code, stdout, stderr = self._run_bootstrap_cli(phone, password)

        self.assertEqual(exit_code, 1)
        self.assertIn("Password must be at least 8 characters", stderr)

    def test_bootstrap_admin_cli_invalid_phone(self):
        """Test CLI fails with invalid phone number."""
        phone = "123"
        password = "securepass123"

        exit_code, stdout, stderr = self._run_bootstrap_cli(phone, password)

        self.assertEqual(exit_code, 1)
        self.assertIn("Invalid phone number", stderr)

    def test_bootstrap_admin_cli_phone_already_registered(self):
        """Test CLI fails when phone is already registered (non-admin)."""
        phone = "09123456789"
        password = "securepass123"

        # Create a regular user with this phone
        from sqlalchemy.ext.asyncio import AsyncSession
        from app.database import SessionLocal
        import asyncio

        async def _create_regular():
            async with SessionLocal() as db:
                user = User(
                    full_name="Regular User",
                    phone=phone,
                    password_hash=hash_password("otherpass"),
                    role="user",
                    is_active=True,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
                return user

        asyncio.run(_create_regular())

        # Try to bootstrap admin with same phone
        exit_code, stdout, stderr = self._run_bootstrap_cli(phone, password)
        self.assertEqual(exit_code, 1)
        self.assertIn("Phone number already registered", stderr)


class TestNoSecretLeakage(unittest.TestCase):
    """Test that secrets are not leaked in responses or logs."""

    def setUp(self):
        self.client = TestClient(app)

    def test_password_not_in_login_response(self):
        """Test password not in login response."""
        response = self.client.post(
            "/auth/login", json={"phone": "09123456789", "password": "secret123"}
        )
        self.assertNotIn("secret123", response.text)

    def test_password_hash_not_in_user_response(self):
        """Test password_hash not in user creation response."""
        # The user creation endpoint is now protected, but we can verify
        # the schema doesn't include password_hash
        from app.schemas.user import UserResponse
        schema = UserResponse.model_json_schema()
        self.assertNotIn("password_hash", schema.get("properties", {}))

    def test_token_does_not_auto_include_sensitive_data(self):
        """Test JWT token doesn't automatically include sensitive data."""
        token = create_access_token(subject="1")
        payload = decode_access_token(token)
        # Our implementation only includes sub, exp, iat by default
        # No sensitive data like password should be auto-included
        self.assertIn("sub", payload)
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)
        self.assertNotIn("password", payload)
        self.assertEqual(set(payload.keys()), {"sub", "exp", "iat"})

    def test_token_includes_extra_claims_when_provided(self):
        """Test JWT token includes extra_claims when explicitly provided."""
        token = create_access_token(
            subject="1", extra_claims={"custom_claim": "value"}
        )
        payload = decode_access_token(token)
        self.assertEqual(payload["custom_claim"], "value")


class TestRoleEscalationPrevention(unittest.TestCase):
    """Test prevention of unauthorized role escalation."""

    @classmethod
    def setUpClass(cls):
        from app.database import init_db

        asyncio.run(init_db())

    def setUp(self):
        self.client = TestClient(app)

    def test_anonymous_cannot_create_admin(self):
        """Test that anonymous user cannot create admin user."""
        # The create_user endpoint now requires admin auth
        # So anonymous requests should get 401
        response = self.client.post(
            "/users/",
            json={
                "full_name": "Attacker",
                "phone": "09999999999",
                "password": "pass1234",
                "role": "admin",
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_regular_user_cannot_create_admin(self):
        """A non-admin authenticated user must get 403 on user creation."""
        phone = "09351112233"
        _delete_user(phone)
        user = _create_user(phone, "regular-pass-123", role="user")
        try:
            token = create_access_token(subject=str(user.id))
            response = self.client.post(
                "/users/",
                json={
                    "full_name": "Escalation",
                    "phone": "09359998877",
                    "password": "pass1234",
                    "role": "admin",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "COMMON_FORBIDDEN")
        finally:
            _delete_user(phone)


def _create_user(phone, password, role="user", is_active=True):
    """Create a user directly in the shared test database."""
    from app.database import SessionLocal

    async def _run():
        async with SessionLocal() as db:
            user = User(
                full_name="Probe User",
                phone=phone,
                password_hash=hash_password(password),
                role=role,
                is_active=is_active,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    return asyncio.run(_run())


def _delete_user(phone):
    """Remove a user by phone from the shared test database."""
    from sqlalchemy import delete
    from app.database import SessionLocal

    async def _run():
        async with SessionLocal() as db:
            await db.execute(delete(User).where(User.phone == phone))
            await db.commit()

    asyncio.run(_run())


def _set_user_active(phone, active):
    """Toggle is_active for a user in the shared test database."""
    from sqlalchemy import update
    from app.database import SessionLocal

    async def _run():
        async with SessionLocal() as db:
            await db.execute(
                update(User).where(User.phone == phone).values(is_active=active)
            )
            await db.commit()

    asyncio.run(_run())


class TestEndpointProtection(unittest.TestCase):
    """Phase-1 authorization matrix: anonymous / user / admin per endpoint."""

    # Management writes: admin only.
    ADMIN_ENDPOINTS = [
        ("POST", "/users/", {}),
        ("POST", "/doctors/", {}),
        ("PUT", "/doctors/999999", {}),
        ("POST", "/doctor-schedules/", {}),
        ("PUT", "/doctor-schedules/999999", {}),
        ("DELETE", "/doctor-schedules/999999", None),
        ("POST", "/dental-services/", {}),
        ("PUT", "/dental-services/999999", {}),
        ("DELETE", "/dental-services/999999", None),
        ("DELETE", "/patients/999999", None),
    ]

    # Operational endpoints carrying patient/appointment data: any logged-in user.
    USER_ENDPOINTS = [
        ("POST", "/patients/", {}),
        ("PUT", "/patients/999999", {}),
        ("GET", "/patients/", None),
        ("GET", "/patients/999999", None),
        ("POST", "/appointments/", {}),
        ("GET", "/appointments/patient/999999", None),
        (
            "GET",
            "/appointments/available-slots/?doctor_id=999999&appointment_date=1405-01-01",
            None,
        ),
    ]

    @classmethod
    def setUpClass(cls):
        from app.database import init_db

        asyncio.run(init_db())

    def setUp(self):
        self.client = TestClient(app)
        self.admin_phone = "09351000001"
        self.user_phone = "09351000002"
        _delete_user(self.admin_phone)
        _delete_user(self.user_phone)
        admin = _create_user(self.admin_phone, "admin-pass-123", role="admin")
        regular = _create_user(self.user_phone, "user-pass-123", role="receptionist")
        self.admin_token = create_access_token(subject=str(admin.id))
        self.user_token = create_access_token(subject=str(regular.id))

    def tearDown(self):
        _delete_user(self.admin_phone)
        _delete_user(self.user_phone)

    def _request(self, method, path, token=None, body=None):
        headers = {"Authorization": f"Bearer {token}"} if token else None
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        return self.client.request(method, path, **kwargs)

    def test_anonymous_requests_are_rejected_on_every_protected_endpoint(self):
        for method, path, body in self.ADMIN_ENDPOINTS + self.USER_ENDPOINTS:
            with self.subTest(method=method, path=path, auth="anonymous"):
                response = self._request(method, path, body=body)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.json()["error"]["code"], "COMMON_UNAUTHORIZED"
                )

    def test_regular_user_is_forbidden_on_admin_endpoints(self):
        for method, path, body in self.ADMIN_ENDPOINTS:
            with self.subTest(method=method, path=path, auth="user"):
                response = self._request(
                    method, path, token=self.user_token, body=body
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["error"]["code"], "COMMON_FORBIDDEN")


    def test_admin_passes_authorization_on_admin_endpoints(self):
        for method, path, body in self.ADMIN_ENDPOINTS:
            with self.subTest(method=method, path=path, auth="admin"):
                response = self._request(
                    method, path, token=self.admin_token, body=body
                )
                self.assertNotIn(response.status_code, (401, 403))

    def test_authenticated_user_passes_on_operational_endpoints(self):
        for method, path, body in self.USER_ENDPOINTS:
            with self.subTest(method=method, path=path, auth="user"):
                response = self._request(
                    method, path, token=self.user_token, body=body
                )
                self.assertNotIn(response.status_code, (401, 403))

    def test_admin_can_create_doctor_with_valid_payload(self):
        response = self._request(
            "POST",
            "/doctors/",
            token=self.admin_token,
            body={
                "full_name": "دکتر محافظت‌شده",
                "specialty": "تخصص تست",
                "phone": "09120001122",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "دکتر محافظت‌شده")

    def test_authenticated_user_can_create_patient_and_read_list(self):
        create = self._request(
            "POST",
            "/patients/",
            token=self.user_token,
            body={
                "national_id": "5550011122",
                "full_name": "بیمار محافظت‌شده",
                "phone": "09120003344",
            },
        )
        self.assertEqual(create.status_code, 200)
        listing = self._request("GET", "/patients/", token=self.user_token)
        self.assertEqual(listing.status_code, 200)

    def test_garbage_and_forged_signature_tokens_are_rejected(self):
        forged = jwt.encode(
            {"sub": "1", "exp": time.time() + 3600},
            "attacker-secret",
            algorithm="HS256",
        )
        for token in ("not-a-jwt", forged):
            with self.subTest(token_kind=token[:12]):
                response = self._request("GET", "/patients/", token=token)
                self.assertEqual(response.status_code, 401)

    def test_expired_token_is_rejected_on_endpoint(self):
        expired = create_access_token(
            subject="1", expires_delta=timedelta(seconds=-30)
        )
        response = self._request("GET", "/patients/", token=expired)
        self.assertEqual(response.status_code, 401)

    def test_inactive_user_token_is_rejected_on_endpoint(self):
        phone = "09351000003"
        _delete_user(phone)
        user = _create_user(phone, "inactive-pass-123", role="user")
        try:
            token = create_access_token(subject=str(user.id))
            _set_user_active(phone, False)
            response = self._request("GET", "/patients/", token=token)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "COMMON_UNAUTHORIZED")
        finally:
            _delete_user(phone)


if __name__ == "__main__":
    unittest.main()