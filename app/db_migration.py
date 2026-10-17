"""Explicit, additive SQLite schema migrations.

Every migration here is additive and idempotent: columns are only added when
missing, indexes are created with IF NOT EXISTS, and existing rows and IDs
are never touched. See README for the backup and upgrade procedure.
"""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection


async def _table_columns(conn: AsyncConnection, table: str) -> set[str]:
    return await conn.run_sync(
        lambda sync_conn: {
            column["name"]
            for column in inspect(sync_conn).get_columns(table)
        }
    )


async def run_additive_migrations(conn: AsyncConnection) -> None:
    """Add the patient ownership link used by authorization checks."""
    if conn.dialect.name != "sqlite":
        return

    if "user_id" not in await _table_columns(conn, "patients"):
        await conn.execute(
            text("ALTER TABLE patients ADD COLUMN user_id INTEGER REFERENCES users(id)")
        )
    await conn.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS ix_patients_user_id ON patients (user_id)")
    )
