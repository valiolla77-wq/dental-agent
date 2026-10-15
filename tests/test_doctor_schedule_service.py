import unittest
from datetime import time
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.dependencies import require_admin
from app.database import get_db
from app.errors import AppError
from app.models.base import Base
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.user import User
from app.routers.doctor_schedules import router as doctor_schedules_router
from app.services import doctor_schedule_service


class DoctorScheduleServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def _create_doctor(self) -> Doctor:
        async with self.session_factory() as db:
            doctor = Doctor(
                full_name="دکتر نمونهٔ ساختگی",
                specialty="تخصص نمونه",
                phone="09000000000",
            )
            db.add(doctor)
            await db.commit()
            await db.refresh(doctor)
            return doctor

    async def _create_schedule(
        self,
        doctor_id: int,
        day_of_week: int = 1,
        start_time: time = time(9, 0),
        end_time: time = time(13, 0),
        slot_duration_minutes: int = 30,
    ) -> DoctorSchedule:
        async with self.session_factory() as db:
            return await doctor_schedule_service.create_doctor_schedule(
                db=db,
                doctor_id=doctor_id,
                day_of_week=day_of_week,
                start_time=start_time,
                end_time=end_time,
                slot_duration_minutes=slot_duration_minutes,
            )

    async def test_create_schedule_for_existing_doctor(self):
        doctor = await self._create_doctor()
        schedule = await self._create_schedule(doctor.id)

        self.assertIsInstance(schedule, DoctorSchedule)
        self.assertIsNotNone(schedule.id)
        self.assertEqual(schedule.doctor_id, doctor.id)
        self.assertEqual(schedule.day_of_week, 1)
        self.assertEqual(schedule.start_time, time(9, 0))
        self.assertEqual(schedule.end_time, time(13, 0))
        self.assertEqual(schedule.slot_duration_minutes, 30)
        self.assertTrue(schedule.is_active)

    async def test_create_schedule_for_missing_doctor_raises_catalog_error(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await doctor_schedule_service.create_doctor_schedule(
                    db=db,
                    doctor_id=999,
                    day_of_week=1,
                    start_time=time(9, 0),
                    end_time=time(13, 0),
                    slot_duration_minutes=30,
                )

        self.assertEqual(raised.exception.code, "DOCTOR_NOT_FOUND")

    async def test_list_schedules_for_existing_doctor(self):
        doctor = await self._create_doctor()
        await self._create_schedule(doctor.id, day_of_week=3)
        await self._create_schedule(doctor.id, day_of_week=1)

        async with self.session_factory() as db:
            schedules = await doctor_schedule_service.list_doctor_schedules(
                db,
                doctor.id,
            )

        self.assertEqual([schedule.day_of_week for schedule in schedules], [1, 3])
        self.assertTrue(all(schedule.doctor_id == doctor.id for schedule in schedules))

    async def test_list_schedules_for_missing_doctor_returns_empty_list(self):
        async with self.session_factory() as db:
            schedules = await doctor_schedule_service.list_doctor_schedules(
                db,
                999,
            )

        self.assertEqual(schedules, [])

    async def test_update_schedule_changes_all_mutable_fields(self):
        doctor = await self._create_doctor()
        schedule = await self._create_schedule(doctor.id)

        async with self.session_factory() as db:
            updated = await doctor_schedule_service.update_doctor_schedule(
                db=db,
                schedule_id=schedule.id,
                day_of_week=4,
                start_time=time(10, 15),
                end_time=time(14, 45),
                slot_duration_minutes=20,
                is_active=False,
            )

        self.assertEqual(updated.id, schedule.id)
        self.assertEqual(updated.doctor_id, doctor.id)
        self.assertEqual(updated.day_of_week, 4)
        self.assertEqual(updated.start_time, time(10, 15))
        self.assertEqual(updated.end_time, time(14, 45))
        self.assertEqual(updated.slot_duration_minutes, 20)
        self.assertFalse(updated.is_active)

    async def test_update_missing_schedule_raises_catalog_error(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await doctor_schedule_service.update_doctor_schedule(
                    db=db,
                    schedule_id=999,
                    day_of_week=1,
                    start_time=time(9, 0),
                    end_time=time(13, 0),
                    slot_duration_minutes=30,
                    is_active=True,
                )

        self.assertEqual(raised.exception.code, "DOCTOR_SCHEDULE_NOT_FOUND")

    async def test_delete_schedule_removes_it_and_returns_its_id(self):
        doctor = await self._create_doctor()
        schedule = await self._create_schedule(doctor.id)

        async with self.session_factory() as db:
            deleted_id = await doctor_schedule_service.delete_doctor_schedule(
                db,
                schedule.id,
            )
            deleted_schedule = await db.get(DoctorSchedule, schedule.id)

        self.assertEqual(deleted_id, schedule.id)
        self.assertIsNone(deleted_schedule)

    async def test_delete_missing_schedule_raises_catalog_error(self):
        async with self.session_factory() as db:
            with self.assertRaises(AppError) as raised:
                await doctor_schedule_service.delete_doctor_schedule(db, 999)

        self.assertEqual(raised.exception.code, "DOCTOR_SCHEDULE_NOT_FOUND")


class DoctorScheduleRouterContractTests(unittest.TestCase):
    def test_create_response_and_status_are_preserved(self):
        app = FastAPI()
        app.include_router(doctor_schedules_router)

        async def fake_db():
            yield None

        async def fake_admin():
            return User(
                full_name="Test Admin",
                phone="09000000099",
                password_hash="unused-hash",
                role="admin",
                is_active=True,
            )

        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[require_admin] = fake_admin
        schedule = DoctorSchedule(
            id=31,
            doctor_id=7,
            day_of_week=2,
            start_time=time(9, 0),
            end_time=time(12, 0),
            slot_duration_minutes=30,
            is_active=True,
        )

        with patch(
            "app.routers.doctor_schedules.doctor_schedule_service.create_doctor_schedule",
            new=AsyncMock(return_value=schedule),
        ) as create_schedule:
            with TestClient(app) as client:
                response = client.post(
                    "/doctor-schedules/",
                    json={
                        "doctor_id": 7,
                        "day_of_week": 2,
                        "start_time": "09:00:00",
                        "end_time": "12:00:00",
                        "slot_duration_minutes": 30,
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "id": 31,
                "doctor_id": 7,
                "day_of_week": 2,
                "start_time": "09:00:00",
                "end_time": "12:00:00",
                "slot_duration_minutes": 30,
                "is_active": True,
            },
        )
        create_schedule.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
