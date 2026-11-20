import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Load the project's ``.env`` before any module reads configuration. The
# database module is imported by every entry point (server, scripts, tests),
# so this is the earliest shared point that still lets DATABASE_URL,
# JWT_SECRET and provider settings come from ``.env`` as documented in the
# README. ``load_dotenv`` never overrides variables already present in the
# real process environment, so deployment/test overrides keep priority.
load_dotenv()

from app.db_migration import run_additive_migrations  # noqa: E402
from app.models.appointment import Appointment  # noqa: E402
from app.models.base import Base  # noqa: E402

# Allow DATABASE_URL to be configured via environment variable for testing
# Default to the real database file for production
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dental_agent.db")

# Never log SQL parameters by default: they can contain patient identity and
# confirmation arguments. Operators may opt in explicitly for local debugging.
SQL_ECHO = os.getenv("SQL_ECHO", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

engine = create_async_engine(DATABASE_URL, echo=SQL_ECHO)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def ensure_appointment_service_id_required(conn) -> None:
    """Tighten only an empty legacy SQLite table; never delete appointments."""
    if conn.dialect.name != "sqlite":
        return

    appointment_columns = await conn.run_sync(
        lambda sync_conn: {
            column["name"]: column
            for column in inspect(sync_conn).get_columns("appointments")
        }
    )
    service_column = appointment_columns.get("service_id")
    if service_column is not None and not service_column["nullable"]:
        return

    appointment_count = await conn.scalar(
        text("SELECT COUNT(*) FROM appointments")
    )
    if appointment_count:
        raise RuntimeError(
            "The appointments table requires an explicit data migration "
            "before service_id can be made NOT NULL. "
            "No appointment rows were deleted."
        )

    # Rebuild only an empty legacy table; historical appointment data is never
    # removed automatically during application startup.
    await conn.run_sync(
        lambda sync_conn: Appointment.__table__.drop(sync_conn)
    )
    await conn.run_sync(
        lambda sync_conn: Appointment.__table__.create(sync_conn)
    )


async def database_is_ready() -> bool:
    """Return True when a trivial query succeeds on the configured database.

    Used by ``/health/ready`` and the admin system-health page. The exception is
    swallowed on purpose: readiness must return a status, never a 500, and the
    error text can contain the database URL or credentials.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await run_additive_migrations(conn)
        await ensure_appointment_service_id_required(conn)



async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
