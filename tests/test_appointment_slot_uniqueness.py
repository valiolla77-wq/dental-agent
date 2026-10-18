"""Database-level tests for appointment slot uniqueness and migration safety.

All tests use temporary SQLite files, never the real database. Concurrency
tests use independent AsyncSessions and force both requests through slot
validation before either inserts, so the database constraint (not the
pre-check) is what decides the winner.
"""

import asyncio
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import db_migration
from app.errors import AppError
from app.models.appointment import APPOINTMENT_SLOT_INDEX, Appointment
from app.models.base import Base
from app.models.dental_service import DentalService
from app.models.doctor import Doctor
from app.models.doctor_schedule import DoctorSchedule
from app.models.patient import Patient
from app.services import appointment_service, booking_service
from app.utils.date_utils import gregorian_to_jalali


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


class AppointmentSlotUniquenessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tempdir.name) / "slots.db"
        self.engine = create_async_engine(
            _url(self.db_path), connect_args={"timeout": 10}
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.jalali_date = gregorian_to_jalali(
            datetime(2026, 10, 10, 0, 0)
        )[0]

        async with self.factory() as db:
            service = DentalService(name="خدمت تست Slot", is_active=True)
            db.add(service)
            await db.flush()
            doctor_one = Doctor(
                full_name="دکتر تست Slot یک",
                specialty="تخصص تست",
                phone="09360004001",
                is_active=True,
                dental_services=[service],
            )
            doctor_two = Doctor(
                full_name="دکتر تست Slot دو",
                specialty="تخصص تست",
                phone="09360004002",
                is_active=True,
                dental_services=[service],
            )
            db.add_all([doctor_one, doctor_two])
            await db.flush()
            patient_one = Patient(
                national_id="9400000001",
                full_name="بیمار تست Slot یک",
                phone="09360004003",
            )
            patient_two = Patient(
                national_id="9400000002",
                full_name="بیمار تست Slot دو",
                phone="09360004004",
            )
            db.add_all([patient_one, patient_two])
            for doctor in (doctor_one, doctor_two):
                db.add(
                    DoctorSchedule(
                        doctor_id=doctor.id,
                        day_of_week=0,
                        start_time=time(9),
                        end_time=time(13),
                        slot_duration_minutes=30,
                        is_active=True,
                    )
                )
            await db.commit()
            self.service_id = service.id
            self.doctor_one_id = doctor_one.id
            self.doctor_two_id = doctor_two.id
            self.patient_one_id = patient_one.id
            self.patient_two_id = patient_two.id

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def _book(self, doctor_id, patient_id, clock):
        async with self.factory() as db:
            return await booking_service.create_booking(
                db,
                doctor_id=doctor_id,
                service_id=self.service_id,
                appointment_date=self.jalali_date,
                appointment_time=clock,
                patient_id=patient_id,
            )

    @staticmethod
    def _barrier_validation():
        """Let both concurrent requests pass validation before inserting."""
        original = appointment_service._validate_appointment_slot
        barrier = asyncio.Barrier(2)

        async def wrapped(*args, **kwargs):
            result = await original(*args, **kwargs)
            await barrier.wait()
            return result

        return patch.object(
            appointment_service, "_validate_appointment_slot", new=wrapped
        )

    async def _appointments(self, doctor_id):
        async with self.factory() as db:
            return list(
                (
                    await db.execute(
                        select(Appointment)
                        .where(Appointment.doctor_id == doctor_id)
                        .order_by(Appointment.appointment_time)
                    )
                )
                .scalars()
                .all()
            )

    async def test_concurrent_same_slot_allows_exactly_one_booking(self):
        with self._barrier_validation():
            results = await asyncio.gather(
                self._book(
                    self.doctor_one_id, self.patient_one_id, "09:00"
                ),
                self._book(
                    self.doctor_one_id, self.patient_two_id, "09:00"
                ),
                return_exceptions=True,
            )

        successes = [item for item in results if isinstance(item, Appointment)]
        failures = [item for item in results if isinstance(item, AppError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].code, "APPOINTMENT_SLOT_BOOKED")

        rows = await self._appointments(self.doctor_one_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "scheduled")
        self.assertEqual(rows[0].appointment_time, datetime(2026, 10, 10, 9, 0))

    async def test_concurrent_different_doctors_same_time_both_succeed(self):
        with self._barrier_validation():
            results = await asyncio.gather(
                self._book(
                    self.doctor_one_id, self.patient_one_id, "09:00"
                ),
                self._book(
                    self.doctor_two_id, self.patient_two_id, "09:00"
                ),
                return_exceptions=True,
            )

        self.assertEqual(
            [type(item).__name__ for item in results],
            ["Appointment", "Appointment"],
        )
        self.assertEqual(len(await self._appointments(self.doctor_one_id)), 1)
        self.assertEqual(len(await self._appointments(self.doctor_two_id)), 1)

    async def test_adjacent_fixed_slots_for_same_doctor_are_allowed(self):
        with self._barrier_validation():
            results = await asyncio.gather(
                self._book(
                    self.doctor_one_id, self.patient_one_id, "09:00"
                ),
                self._book(
                    self.doctor_one_id, self.patient_two_id, "09:30"
                ),
                return_exceptions=True,
            )

        self.assertTrue(
            all(isinstance(item, Appointment) for item in results)
        )
        self.assertEqual(len(await self._appointments(self.doctor_one_id)), 2)

    async def test_cancelled_appointment_releases_slot_for_rebooking(self):
        appointment = await self._book(
            self.doctor_one_id, self.patient_one_id, "09:00"
        )
        async with self.factory() as db:
            stored = await db.get(Appointment, appointment.id)
            stored.status = "cancelled"
            await db.commit()

        replacement = await self._book(
            self.doctor_one_id, self.patient_two_id, "09:00"
        )
        self.assertNotEqual(replacement.id, appointment.id)

        rows = await self._appointments(self.doctor_one_id)
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(row.status for row in rows), ["cancelled", "scheduled"]
        )

    async def test_reschedule_db_conflict_preserves_previous_time(self):
        first = await self._book(
            self.doctor_one_id, self.patient_one_id, "09:00"
        )
        second = await self._book(
            self.doctor_one_id, self.patient_two_id, "09:30"
        )
        self.assertIsNotNone(second)
        occupied = datetime(2026, 10, 10, 9, 30)

        # Bypass the service pre-check so the database constraint is what
        # rejects the conflicting UPDATE.
        with patch.object(
            appointment_service,
            "_validate_appointment_slot",
            new=AsyncMock(return_value=occupied),
        ):
            with self.assertRaises(AppError) as caught:
                async with self.factory() as db:
                    await appointment_service.reschedule_appointment(
                        db, first.id, self.jalali_date, "09:30"
                    )

        self.assertEqual(caught.exception.code, "APPOINTMENT_SLOT_BOOKED")
        async with self.factory() as db:
            stored = await db.get(Appointment, first.id)
        self.assertEqual(
            stored.appointment_time, datetime(2026, 10, 10, 9, 0)
        )

    def test_only_the_appointment_slot_constraint_is_mapped(self):
        slot_error = IntegrityError(
            "stmt",
            {},
            Exception(
                "UNIQUE constraint failed: appointments.doctor_id, "
                "appointments.appointment_time"
            ),
        )
        unrelated_error = IntegrityError(
            "stmt", {}, Exception("UNIQUE constraint failed: users.phone")
        )
        self.assertTrue(
            appointment_service._is_appointment_slot_conflict(slot_error)
        )
        self.assertFalse(
            appointment_service._is_appointment_slot_conflict(
                unrelated_error
            )
        )


class AppointmentSlotMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tempdir.name) / "migration.db"
        self.engine = create_async_engine(_url(self.db_path))
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            # Simulate a legacy database that predates the unique index.
            await connection.execute(
                text(f"DROP INDEX IF EXISTS {APPOINTMENT_SLOT_INDEX}")
            )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def _index_names(self):
        async with self.engine.begin() as connection:
            return {
                index["name"]
                for index in await connection.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_indexes(
                        "appointments"
                    )
                )
            }

    async def _appointment_count(self):
        async with self.engine.begin() as connection:
            return await connection.scalar(
                text("SELECT COUNT(*) FROM appointments")
            )

    async def test_migration_creates_unique_slot_index(self):
        async with self.engine.begin() as connection:
            await db_migration.run_additive_migrations(connection)
        self.assertIn(APPOINTMENT_SLOT_INDEX, await self._index_names())

    async def test_migration_aborts_on_existing_duplicate_scheduled_slots(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO appointments "
                    "(patient_id, doctor_id, service_id, appointment_time, status) "
                    "VALUES "
                    "(1, 1, 1, '2026-10-10 09:00:00', 'scheduled'), "
                    "(2, 1, 1, '2026-10-10 09:00:00', 'scheduled')"
                )
            )
            with self.assertRaisesRegex(
                RuntimeError, "duplicate slots"
            ):
                await db_migration.run_additive_migrations(connection)

        self.assertEqual(await self._appointment_count(), 2)
        self.assertNotIn(APPOINTMENT_SLOT_INDEX, await self._index_names())

    async def test_cancelled_duplicates_do_not_block_migration(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO appointments "
                    "(patient_id, doctor_id, service_id, appointment_time, status) "
                    "VALUES "
                    "(1, 1, 1, '2026-10-10 09:00:00', 'cancelled'), "
                    "(2, 1, 1, '2026-10-10 09:00:00', 'cancelled')"
                )
            )
            await db_migration.run_additive_migrations(connection)

        self.assertEqual(await self._appointment_count(), 2)
        self.assertIn(APPOINTMENT_SLOT_INDEX, await self._index_names())


if __name__ == "__main__":
    unittest.main()
