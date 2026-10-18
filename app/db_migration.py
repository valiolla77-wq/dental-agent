"""Explicit, additive SQLite schema migrations.

Every migration here is additive and idempotent: columns are only added when
missing, indexes are created with IF NOT EXISTS, and existing rows and IDs
are never touched. A migration that cannot be applied without changing
existing data aborts with a clear error instead of modifying rows.
"""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.appointment import APPOINTMENT_SLOT_INDEX


async def _table_columns(conn: AsyncConnection, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"]
            for column in inspect(sync_conn).get_columns(table)
        }
    )


async def _table_indexes(conn: AsyncConnection, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            index["name"]
            for index in inspect(sync_conn).get_indexes(table)
        }
    )


async def _ensure_appointment_slot_index(conn: AsyncConnection) -> None:
    """Create the partial unique slot index or abort on legacy duplicates."""
    columns = await _table_columns(conn, "appointments")
    if not {"doctor_id", "appointment_time", "status"} <= columns:
        return
    if APPOINTMENT_SLOT_INDEX in await _table_indexes(conn, "appointments"):
        return

    duplicates = (
        await conn.execute(
            text(
                "SELECT doctor_id, appointment_time, COUNT(*) AS row_count "
                "FROM appointments "
                "WHERE status = 'scheduled' "
                "GROUP BY doctor_id, appointment_time "
                "HAVING COUNT(*) > 1 "
                "ORDER BY doctor_id, appointment_time "
                "LIMIT 5"
            )
        )
    ).all()
    if duplicates:
        sample = "; ".join(
            f"doctor_id={row.doctor_id}, appointment_time={row.appointment_time}, "
            f"count={row.row_count}"
            for row in duplicates
        )
        raise RuntimeError(
            "Cannot create the unique appointment slot index: existing "
            f"scheduled duplicate slots were found ({sample}). "
            "No appointment rows were modified."
        )

    await conn.execute(
        text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {APPOINTMENT_SLOT_INDEX} "
            "ON appointments (doctor_id, appointment_time) "
            "WHERE status = 'scheduled'"
        )
    )


async def run_additive_migrations(conn: AsyncConnection) -> None:
    """Apply additive schema changes without touching existing rows."""
    if conn.dialect.name != "sqlite":
        return

    if "user_id" not in await _table_columns(conn, "patients"):
        await conn.execute(
            text("ALTER TABLE patients ADD COLUMN user_id INTEGER REFERENCES users(id)")
        )
    await conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS ix_patients_user_id ON patients (user_id)")
    )
    await _ensure_appointment_slot_index(conn)
