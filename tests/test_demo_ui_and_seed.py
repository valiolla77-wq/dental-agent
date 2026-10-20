"""Tests for the browser demo page and the demo database seeder."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.user import User
from scripts import seed_demo


class DemoChatPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_demo_chat_page_is_served_same_origin(self):
        response = self.client.get("/demo")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        body = response.text
        for marker in (
            "ورود بیمار",
            "/auth/otp/request",
            "/auth/otp/verify",
            "/agent/chat",
            "confirmationPane",
            "confirmation",
            "session_id",
        ):
            self.assertIn(marker, body)

    def test_demo_page_does_not_expose_provider_secrets(self):
        body = self.client.get("/demo").text
        for forbidden in (
            "AGENT_LLM_API_KEY",
            "OPENROUTER_API_KEY",
            "localhost:20128",
            "sk-",
        ):
            self.assertNotIn(forbidden, body)


class DemoSeedSafetyTests(unittest.TestCase):
    def test_rejects_missing_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            with self.assertRaises(SystemExit):
                seed_demo.validate_demo_database_url()

    def test_rejects_production_or_unrelated_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rejected = (
                "sqlite+aiosqlite:///:memory:",
                "sqlite+aiosqlite:///./dental_agent.db",
                f"sqlite+aiosqlite:///{(root / 'other.db').as_posix()}",
                f"sqlite+aiosqlite:///{(root / 'demo.sqlite').as_posix()}",
            )
            for url in rejected:
                with self.subTest(url=url):
                    with self.assertRaises(SystemExit):
                        seed_demo.validate_demo_database_url(
                            url, project_root=root
                        )

    def test_accepts_only_project_demo_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = f"sqlite+aiosqlite:///{(root / 'demo.db').as_posix()}"
            self.assertEqual(
                seed_demo.validate_demo_database_url(url, project_root=root),
                url,
            )

    def test_rejects_non_sqlite_url(self):
        with self.assertRaises(SystemExit):
            seed_demo.validate_demo_database_url(
                "postgresql+asyncpg://localhost/demo"
            )


class DemoSeedIdempotencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.factory()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def _count(self, model):
        return await self.db.scalar(select(func.count()).select_from(model))

    async def test_repeated_seed_creates_no_duplicate_rows(self):
        first = await seed_demo.seed_demo(self.db)
        self.assertTrue(first["admin_created"])
        self.assertTrue(first["doctor_created"])
        self.assertTrue(first["service_created"])
        self.assertTrue(first["patient_created"])
        self.assertEqual(first["doctors_created"], 2)
        self.assertEqual(first["services_created"], 3)
        self.assertEqual(first["links_created"], 6)
        self.assertEqual(first["schedules_created"], 14)

        second = await seed_demo.seed_demo(self.db)
        self.assertFalse(second["admin_created"])
        self.assertFalse(second["doctor_created"])
        self.assertFalse(second["service_created"])
        self.assertFalse(second["patient_created"])
        self.assertFalse(second["patient_user_created"])
        self.assertEqual(second["doctors_created"], 0)
        self.assertEqual(second["services_created"], 0)
        self.assertEqual(second["links_created"], 0)
        self.assertEqual(second["schedules_created"], 0)

        self.assertEqual(await self._count(User), 2)
        self.assertEqual(await self._count(Patient), 1)
        self.assertEqual(await self._count(Doctor), 2)
        self.assertEqual(await self._count(DentalService), 3)
        self.assertEqual(await self._count(DoctorSchedule), 14)
        link_count = await self.db.scalar(
            select(func.count()).select_from(doctor_dental_services)
        )
        self.assertEqual(link_count, 6)

        patient = await self.db.scalar(select(Patient))
        patient_user = await self.db.scalar(
            select(User).where(User.id == patient.user_id)
        )
        self.assertEqual(patient_user.phone, seed_demo.DEMO_PATIENT_PHONE)
        self.assertEqual(patient_user.role, "patient")


if __name__ == "__main__":
    unittest.main()
