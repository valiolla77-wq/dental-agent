"""Tests for the local sample-data seeder (never used by the product)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.appointment import Appointment
from app.models.base import Base
from app.models.clinical_entry import ClinicalEntry
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_dental_service import doctor_dental_services
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.models.tooth_status import ToothStatus
from app.models.treatment_plan import TreatmentPlanItem
from app.models.user import User
from scripts import seed_sample


class SampleSeedSafetyTests(unittest.TestCase):
    def test_rejects_missing_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": ""}, clear=False):
            with self.assertRaises(SystemExit):
                seed_sample.validate_sample_database_url()

    def test_rejects_production_or_unrelated_database_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rejected = (
                "sqlite+aiosqlite:///:memory:",
                "sqlite+aiosqlite:///./dental_agent.db",
                f"sqlite+aiosqlite:///{(root / 'other.db').as_posix()}",
                f"sqlite+aiosqlite:///{(root / 'sample.sqlite').as_posix()}",
            )
            for url in rejected:
                with self.subTest(url=url):
                    with self.assertRaises(SystemExit):
                        seed_sample.validate_sample_database_url(
                            url, project_root=root
                        )

    def test_accepts_only_project_sample_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            url = f"sqlite+aiosqlite:///{(root / 'sample.db').as_posix()}"
            self.assertEqual(
                seed_sample.validate_sample_database_url(url, project_root=root),
                url,
            )

    def test_rejects_non_sqlite_url(self):
        with self.assertRaises(SystemExit):
            seed_sample.validate_sample_database_url(
                "postgresql+asyncpg://localhost/sample"
            )


class SampleSeedIdempotencyTests(unittest.IsolatedAsyncioTestCase):
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
        first = await seed_sample.seed_sample(self.db)
        self.assertTrue(first["admin_created"])
        self.assertTrue(first["doctor_created"])
        self.assertTrue(first["service_created"])
        self.assertTrue(first["patient_created"])
        self.assertEqual(first["doctors_created"], 2)
        self.assertEqual(first["services_created"], 3)
        self.assertEqual(first["links_created"], 6)
        self.assertEqual(first["schedules_created"], 14)
        self.assertEqual(first["patients_created"], 10)
        self.assertEqual(first["appointments_created"], 10)
        self.assertEqual(first["prescriptions_created"], 4)
        self.assertEqual(first["plan_items_created"], 6)

        second = await seed_sample.seed_sample(self.db)
        self.assertFalse(second["admin_created"])
        self.assertFalse(second["doctor_created"])
        self.assertFalse(second["service_created"])
        self.assertFalse(second["patient_created"])
        self.assertFalse(second["patient_user_created"])
        self.assertEqual(second["doctors_created"], 0)
        self.assertEqual(second["services_created"], 0)
        self.assertEqual(second["links_created"], 0)
        self.assertEqual(second["schedules_created"], 0)
        self.assertEqual(second["patients_created"], 0)
        self.assertEqual(second["appointments_created"], 0)
        self.assertEqual(second["prescriptions_created"], 0)
        self.assertEqual(second["plan_items_created"], 0)

        # Admin + patient + receptionist + doctor account (linked to the
        # first doctor record) — the four portals' personas.
        self.assertEqual(await self._count(User), 4)
        # The sample patient account plus the ten walk-in records.
        self.assertEqual(await self._count(Patient), 11)
        self.assertEqual(await self._count(Doctor), 2)
        self.assertEqual(await self._count(DentalService), 3)
        self.assertEqual(await self._count(DoctorSchedule), 14)
        link_count = await self.db.scalar(
            select(func.count()).select_from(doctor_dental_services)
        )
        self.assertEqual(link_count, 6)

        self.assertEqual(await self._count(Appointment), 10)
        self.assertEqual(await self._count(ClinicalEntry), 8)
        self.assertEqual(await self._count(ToothStatus), 10)
        self.assertEqual(await self._count(Prescription), 4)
        self.assertEqual(await self._count(TreatmentPlanItem), 6)

        patient = await self.db.scalar(select(Patient))
        patient_user = await self.db.scalar(
            select(User).where(User.id == patient.user_id)
        )
        self.assertEqual(patient_user.phone, seed_sample.SAMPLE_PATIENT_PHONE)
        self.assertEqual(patient_user.role, "patient")

        # The sample doctor account is linked 1:1 to the first doctor record.
        doctor_user = await self.db.scalar(
            select(User).where(User.phone == seed_sample.SAMPLE_DOCTOR_USER_PHONE)
        )
        self.assertEqual(doctor_user.role, "doctor")
        linked_doctor = await self.db.scalar(
            select(Doctor).where(Doctor.user_id == doctor_user.id)
        )
        self.assertIsNotNone(linked_doctor)


if __name__ == "__main__":
    unittest.main()
