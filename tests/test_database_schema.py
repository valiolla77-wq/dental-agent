import unittest

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import ensure_appointment_service_id_required


class AppointmentSchemaUpgradeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql(
                "CREATE TABLE patients (id INTEGER PRIMARY KEY)"
            )
            await connection.exec_driver_sql(
                "CREATE TABLE doctors (id INTEGER PRIMARY KEY)"
            )
            await connection.exec_driver_sql(
                "CREATE TABLE dental_services (id INTEGER PRIMARY KEY)"
            )
            await connection.exec_driver_sql(
                "CREATE TABLE appointments ("
                "id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL, "
                "doctor_id INTEGER NOT NULL, appointment_time DATETIME NOT NULL, "
                "status VARCHAR(20) NOT NULL, reason VARCHAR(500))"
            )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_empty_legacy_table_is_rebuilt_with_required_service_fk(self):
        async with self.engine.begin() as connection:
            await ensure_appointment_service_id_required(connection)
            columns = await connection.run_sync(
                lambda sync_conn: {
                    column["name"]: column
                    for column in inspect(sync_conn).get_columns("appointments")
                }
            )
            foreign_keys = await connection.run_sync(
                lambda sync_conn: inspect(sync_conn).get_foreign_keys("appointments")
            )

        self.assertFalse(columns["service_id"]["nullable"])
        self.assertIn(
            "dental_services",
            {foreign_key["referred_table"] for foreign_key in foreign_keys},
        )

    async def test_nonempty_legacy_table_fails_without_deleting_rows(self):
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql(
                "INSERT INTO appointments "
                "(id, patient_id, doctor_id, appointment_time, status) "
                "VALUES (1, 1, 1, '2026-10-07 09:00:00', 'completed')"
            )
            with self.assertRaisesRegex(RuntimeError, "No appointment rows were deleted"):
                await ensure_appointment_service_id_required(connection)
            count = await connection.scalar(text("SELECT COUNT(*) FROM appointments"))

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
