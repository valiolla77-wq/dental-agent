"""Additive migration tests for the multi-patient User/Patient link."""

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (register every table on Base.metadata)
from app import db_migration
from app.models.base import Base


class PatientLinkMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.tempdir.name) / "patient-link.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            # Simulate a legacy database that predates the unique link index.
            await connection.execute(
                text("DROP INDEX IF EXISTS ix_patients_user_id")
            )

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def _index_names(self):
        async with self.engine.begin() as connection:
            return {
                index["name"]
                for index in await connection.run_sync(
                    lambda sync_conn: inspect(sync_conn).get_indexes("patients")
                )
            }

    async def _patient_count(self):
        async with self.engine.begin() as connection:
            return await connection.scalar(text("SELECT COUNT(*) FROM patients"))

    async def _index_is_unique(self, name="ix_patients_user_id"):
        async with self.engine.begin() as connection:
            indexes = await connection.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes("patients")
            )
        return any(
            index["name"] == name and index.get("unique")
            for index in indexes
        )

    async def test_migration_creates_non_unique_patient_user_index(self):
        async with self.engine.begin() as connection:
            await db_migration.run_additive_migrations(connection)

        self.assertIn("ix_patients_user_id", await self._index_names())
        self.assertFalse(await self._index_is_unique())

    async def test_migration_replaces_same_named_unique_index(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                text("DROP INDEX IF EXISTS ix_patients_user_id")
            )
            await connection.execute(
                text(
                    "CREATE UNIQUE INDEX ix_patients_user_id "
                    "ON patients (user_id)"
                )
            )
            await db_migration.run_additive_migrations(connection)

        self.assertFalse(await self._index_is_unique())

    async def test_migration_allows_duplicate_patient_links(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO patients "
                    "(national_id, full_name, phone, user_id) VALUES "
                    "('1000000001', 'first', '09110000001', 42), "
                    "('1000000002', 'second', '09110000002', 42)"
                )
            )
            await db_migration.run_additive_migrations(connection)

        self.assertEqual(await self._patient_count(), 2)
        self.assertIn("ix_patients_user_id", await self._index_names())
        self.assertFalse(await self._index_is_unique())

    async def test_migration_backfills_the_account_holder(self):
        async with self.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO users (id, full_name, phone, password_hash, role, is_active) "
                    "VALUES (42, 'holder', '09120000042', 'hash', 'patient', 1)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO patients "
                    "(national_id, full_name, phone, user_id, is_account_holder) VALUES "
                    "('1000000003', 'holder', '09120000042', 42, 0), "
                    "('1000000004', 'family', '09120000043', 42, 0)"
                )
            )
            await db_migration.run_additive_migrations(connection)

        async with self.engine.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT full_name, is_account_holder FROM patients "
                        "WHERE user_id = 42 ORDER BY id"
                    )
                )
            ).all()
        self.assertEqual([(row[0], row[1]) for row in rows], [("holder", 1), ("family", 0)])
        self.assertTrue(await self._index_is_unique("uq_patients_account_holder"))

    async def test_migration_aborts_on_duplicate_phones_without_rewriting(self):
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP INDEX IF EXISTS ix_patients_phone"))
            await connection.execute(
                text("CREATE INDEX ix_patients_phone ON patients (phone)")
            )
            await connection.execute(
                text(
                    "INSERT INTO patients "
                    "(national_id, full_name, phone) VALUES "
                    "('1000000005', 'first', '09120000044'), "
                    "('1000000006', 'second', '09120000044')"
                )
            )
            with self.assertRaisesRegex(RuntimeError, "duplicate phone"):
                await db_migration.run_additive_migrations(connection)

        self.assertEqual(await self._patient_count(), 2)
        self.assertFalse(await self._index_is_unique("ix_patients_phone"))


if __name__ == "__main__":
    unittest.main()
