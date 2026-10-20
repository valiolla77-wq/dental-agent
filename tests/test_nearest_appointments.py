"""Deterministic tests for nearest-appointment range search."""

import unittest
from datetime import datetime, time

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agent_tools.tools import find_nearest_appointments
from app.errors import AppError
from app.models.appointment import Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.services import appointment_service, dental_service_service
from app.utils.date_utils import jalali_to_gregorian


class NearestAppointmentSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.factory() as db:
            self.cleaning = DentalService(
                name="جرم‌گیری تست",
                description="پاکسازی جرم و پلاک دندان",
                is_active=True,
            )
            self.filling = DentalService(
                name="ترمیم تست",
                description="بررسی و درمان پوسیدگی دندان",
                is_active=True,
            )
            db.add_all([self.cleaning, self.filling])
            await db.flush()
            self.doctor_one = Doctor(
                full_name="دکتر یک",
                specialty="عمومی",
                phone="09360008001",
                is_active=True,
                dental_services=[self.cleaning, self.filling],
            )
            self.doctor_two = Doctor(
                full_name="دکتر دو",
                specialty="عمومی",
                phone="09360008002",
                is_active=True,
                dental_services=[self.cleaning],
            )
            self.patient = Patient(
                national_id="9800000001",
                full_name="بیمار جست‌وجو",
                phone="09360008003",
            )
            db.add_all([self.doctor_one, self.doctor_two, self.patient])
            await db.flush()
            for doctor in (self.doctor_one, self.doctor_two):
                for day in range(7):
                    db.add(
                        DoctorSchedule(
                            doctor_id=doctor.id,
                            day_of_week=day,
                            start_time=time(9),
                            end_time=time(13),
                            slot_duration_minutes=30,
                            is_active=True,
                        )
                    )
            # Occupied at 09:00; cancelled at 09:30 must become available.
            db.add(
                Appointment(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor_one.id,
                    service_id=self.cleaning.id,
                    appointment_time=datetime(2026, 10, 10, 9, 0),
                    status="scheduled",
                )
            )
            db.add(
                Appointment(
                    patient_id=self.patient.id,
                    doctor_id=self.doctor_one.id,
                    service_id=self.cleaning.id,
                    appointment_time=datetime(2026, 10, 10, 9, 30),
                    status="cancelled",
                )
            )
            await db.commit()
            self.cleaning_id = self.cleaning.id
            self.filling_id = self.filling.id
            self.doctor_one_id = self.doctor_one.id
            self.doctor_two_id = self.doctor_two.id

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _nearest(self, db, **kwargs):
        return await appointment_service.find_nearest_available_slots(db, **kwargs)

    async def test_default_30_day_search_is_sorted_and_limited(self):
        async with self.factory() as db:
            results = await self._nearest(
                db,
                now=datetime(2026, 10, 10, 8, 0),
                limit=3,
            )

        self.assertEqual(len(results), 3)
        self.assertEqual(
            [(item["doctor_id"], item["appointment_time"]) for item in results],
            [
                (self.doctor_two_id, "09:00"),
                (self.doctor_one_id, "09:30"),
                (self.doctor_two_id, "09:30"),
            ],
        )
        slots = [
            jalali_to_gregorian(
                item["appointment_date"], item["appointment_time"]
            )
            for item in results
        ]
        self.assertEqual(slots, sorted(slots))
        self.assertEqual(results[0]["appointment_date"], "1405/07/18")
        self.assertEqual(results[0]["service_name"], "جرم‌گیری تست")

    async def test_past_slots_are_removed(self):
        async with self.factory() as db:
            results = await self._nearest(
                db,
                now=datetime(2026, 10, 10, 10, 15),
                limit=3,
            )

        self.assertEqual(len(results), 3)
        self.assertTrue(
            all(
                datetime.strptime(item["appointment_time"], "%H:%M").time()
                > time(10, 15)
                for item in results
            )
        )
        self.assertEqual(results[0]["appointment_time"], "10:30")

    async def test_no_result_in_range_returns_empty_list(self):
        async with self.factory() as db:
            results = await self._nearest(
                db,
                now=datetime(2026, 10, 10, 13, 0),
                days=1,
            )
        self.assertEqual(results, [])

    async def test_optional_filters_restrict_doctors_and_services(self):
        async with self.factory() as db:
            results = await self._nearest(
                db,
                service_id=self.filling_id,
                doctor_id=self.doctor_one_id,
                now=datetime(2026, 10, 10, 8, 0),
                limit=5,
            )
        self.assertTrue(results)
        self.assertTrue(
            all(
                item["service_id"] == self.filling_id
                and item["doctor_id"] == self.doctor_one_id
                for item in results
            )
        )

        async with self.factory() as db:
            with self.assertRaises(AppError) as caught:
                await self._nearest(
                    db,
                    service_id=self.filling_id,
                    doctor_id=self.doctor_two_id,
                    now=datetime(2026, 10, 10, 8, 0),
                )
        self.assertEqual(caught.exception.code, "APPOINTMENT_DOCTOR_SERVICE_MISMATCH")

    async def test_tool_returns_nearest_structured_results(self):
        async with self.factory() as db:
            result = await find_nearest_appointments(
                db,
                service_id=self.cleaning_id,
                days=30,
                limit=2,
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.data.search_days, 30)
        self.assertEqual(len(result.data.appointments), 2)
        self.assertLessEqual(
            result.data.appointments[0].appointment_time,
            result.data.appointments[1].appointment_time,
        )

    async def test_service_search_matches_description(self):
        async with self.factory() as db:
            results = await dental_service_service.search_dental_services(
                db, "پوسیدگی"
            )
            no_match = await dental_service_service.search_dental_services(
                db, "درد"
            )
        self.assertEqual([item.id for item in results], [self.filling_id])
        self.assertEqual(no_match, [])


if __name__ == "__main__":
    unittest.main()
