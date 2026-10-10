import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import get_db
from app.models.base import Base
from app.models.doctor import Doctor
from app.routers.doctors import router as doctors_router
from app.services import doctor_service


class DoctorServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _create_sample_doctor(self) -> Doctor:
        async with self.session_factory() as db:
            return await doctor_service.create_doctor(
                db=db,
                full_name="دکتر نمونهٔ ساختگی",
                specialty="تخصص نمونه",
                phone="09000000000",
            )

    async def test_create_doctor_returns_model_with_generated_id(self):
        doctor = await self._create_sample_doctor()

        self.assertIsInstance(doctor, Doctor)
        self.assertIsNotNone(doctor.id)

    async def test_create_doctor_persists_supplied_fields(self):
        doctor = await self._create_sample_doctor()

        async with self.session_factory() as db:
            result = await db.execute(
                select(Doctor).where(Doctor.id == doctor.id)
            )
            saved_doctor = result.scalar_one()

        self.assertEqual(saved_doctor.full_name, "دکتر نمونهٔ ساختگی")
        self.assertEqual(saved_doctor.specialty, "تخصص نمونه")
        self.assertEqual(saved_doctor.phone, "09000000000")

    async def test_create_doctor_uses_model_default_for_is_active(self):
        doctor = await self._create_sample_doctor()

        self.assertTrue(doctor.is_active)

    async def test_create_doctor_persists_active_default(self):
        doctor = await self._create_sample_doctor()

        async with self.session_factory() as db:
            saved_doctor = await db.get(Doctor, doctor.id)

        self.assertIsNotNone(saved_doctor)
        self.assertTrue(saved_doctor.is_active)

    def test_create_doctor_api_response_and_status_are_preserved(self):
        app = FastAPI()
        app.include_router(doctors_router)

        async def fake_db():
            yield None

        app.dependency_overrides[get_db] = fake_db
        created_doctor = Doctor(
            id=7,
            full_name="دکتر نمونهٔ ساختگی",
            specialty="تخصص نمونه",
            phone="09000000000",
            is_active=True,
        )

        with patch(
            "app.routers.doctors.doctor_service.create_doctor",
            new=AsyncMock(return_value=created_doctor),
        ) as create_doctor:
            with TestClient(app) as client:
                response = client.post(
                    "/doctors/",
                    json={
                        "full_name": "دکتر نمونهٔ ساختگی",
                        "specialty": "تخصص نمونه",
                        "phone": "09000000000",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": 7,
                "full_name": "دکتر نمونهٔ ساختگی",
                "specialty": "تخصص نمونه",
                "phone": "09000000000",
                "is_active": True,
            },
        )
        create_doctor.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
