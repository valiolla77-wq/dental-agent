"""Staff workspace access, privacy, date boundaries and real database metrics."""
import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.security import create_access_token
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.models.appointment import Appointment
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.patient import Patient
from app.models.user import User


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.db = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.db.add_all([
            User(id=i, full_name=role, role=role, phone=f"0912000000{i}",
                 password_hash="unused", is_active=(i != 6))
            for i, role in enumerate(
                ["admin", "receptionist", "doctor", "patient", "unknown", "admin"], 1)
        ])
        self.db.add_all([
            Patient(id=1, full_name="بیمار آزمایشی", phone="09129999999", national_id="1234567890"),
            Doctor(id=1, full_name="پزشک آزمایشی", specialty="عمومی", phone="09128888888", is_active=True),
            Doctor(id=2, full_name="غیرفعال", specialty="عمومی", phone="09127777777", is_active=False),
            DentalService(id=1, name="معاینه", is_active=True),
        ])
        await self.db.flush()
        self.db.add_all([
            Appointment(id=i, patient_id=1, doctor_id=1, service_id=1,
                        appointment_time=dt, status=status, reason="private reason")
            for i, dt, status in [
                (1, datetime(2026, 10, 22, 0, 0), "scheduled"),
                (2, datetime(2026, 10, 22, 23, 59), "cancelled"),
                (3, datetime(2026, 10, 23, 0, 0), "scheduled"),
            ]
        ])
        await self.db.commit()

        async def override():
            yield self.db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)

    async def asyncTearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.client.close()
        await self.db.close()
        await self.engine.dispose()

    def get(self, user=None, day="2026-10-22"):
        headers = {"Authorization": "Bearer " + create_access_token(subject=str(user))} if user else {}
        return self.client.get("/dashboard/overview?day=" + day, headers=headers)

    async def test_authentication_and_role_boundaries(self):
        self.assertEqual(self.get().status_code, 401)
        for user in [4, 5]:
            self.assertEqual(self.get(user).status_code, 403)
        self.assertEqual(self.get(6).status_code, 401)
        for user in [1, 2, 3]:
            self.assertEqual(self.get(user).status_code, 200)

    async def test_metrics_boundaries_ordering_and_minimum_data(self):
        response = self.get(1)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_appointments"], 2)
        self.assertEqual(data["status_counts"], {"scheduled": 1, "cancelled": 1})
        self.assertEqual(data["total_patients"], 1)
        self.assertEqual(data["active_doctors"], 1)
        self.assertEqual([a["id"] for a in data["appointments"]], [1, 2])
        self.assertEqual(data["appointments"][0]["time"], "00:00")
        for private in ["1234567890", "09129999999", "09128888888", "private reason", "password_hash"]:
            self.assertNotIn(private, response.text)

    async def test_empty_and_invalid_dates(self):
        data = self.get(2, "2026-10-24").json()
        self.assertEqual(data["appointments"], [])
        self.assertEqual(data["total_appointments"], 0)
        self.assertEqual(self.get(1, "invalid").status_code, 422)
        self.assertEqual(self.get(1, "9999-12-31").status_code, 422)
        self.assertEqual(self.get(1).headers["cache-control"], "no-store")

    async def test_public_shell_contains_no_clinic_records(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('dir="rtl"', response.text)
        self.assertIn("/agent/chat", response.text)
        self.assertNotIn("بیمار آزمایشی", response.text)
        self.assertNotIn("localStorage", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
