"""HTTP tests for public probes and the admin system-health summary.

The public probes must stay dependency-free and detail-free. The admin summary
may name providers, but must never return keys, internal URLs, database paths,
or patient data.
"""

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-testing-only-32-chars-long")

from fastapi.testclient import TestClient  # noqa: E402

from app.agent.llm import LLMConfig  # noqa: E402
from app.auth.dependencies import get_current_user  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402


class SystemHealthTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()

    def _as(self, role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: User(
            role=role,
            is_active=True,
            full_name="Test User",
            phone="09120000000",
        )

    def test_liveness_is_dependency_free(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})

    def test_readiness_reports_database(self):
        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"status": "ready", "checks": {"database": "ok"}},
        )

    def test_readiness_is_503_when_database_is_unavailable(self):
        with patch("app.main.database_is_ready", new=AsyncMock(return_value=False)):
            response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertEqual(response.json()["checks"]["database"], "unavailable")

    def test_admin_summary_requires_authentication(self):
        self.assertEqual(self.client.get("/system/health").status_code, 401)

    def test_admin_summary_forbidden_for_non_admin(self):
        self._as("patient")
        self.assertEqual(self.client.get("/system/health").status_code, 403)

    def test_admin_summary_shape_and_no_secret_leak(self):
        self._as("admin")
        secret_config = LLMConfig(
            provider="openrouter",
            model="internal-model",
            base_url="https://internal.example.invalid/v1",
            temperature=0.0,
            api_key="sk-should-never-leak",
        )
        with patch(
            "app.routers.system_health.load_llm_config",
            return_value=secret_config,
        ):
            response = self.client.get("/system/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")
        self.assertEqual(payload["assistant_provider"], "openrouter")
        self.assertTrue(payload["assistant_configured"])
        self.assertGreaterEqual(payload["uptime_seconds"], 0)
        self.assertEqual(payload["version"], app.version)
        self.assertNotIn("internal.example", response.text)
        self.assertNotIn("sk-should-never-leak", response.text)
        self.assertNotIn("internal-model", response.text)
        self.assertNotIn("base_url", payload)
        self.assertNotIn("api_key", payload)

    def test_admin_summary_degrades_without_database(self):
        self._as("admin")
        with patch(
            "app.routers.system_health.database_is_ready",
            new=AsyncMock(return_value=False),
        ):
            response = self.client.get("/system/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["database"], "unavailable")

    def test_admin_summary_when_assistant_unconfigured(self):
        self._as("admin")
        with patch(
            "app.routers.system_health.load_llm_config",
            side_effect=ValueError("missing"),
        ):
            response = self.client.get("/system/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assistant_provider"], "unconfigured")
        self.assertFalse(response.json()["assistant_configured"])


if __name__ == "__main__":
    unittest.main()
