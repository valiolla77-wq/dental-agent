from collections.abc import AsyncGenerator
import os

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.base import Base

# Allow DATABASE_URL to be configured via environment variable for testing
# Default to the real database file for production
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./dental_agent.db")

engine = create_async_engine(DATABASE_URL, echo=True)

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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_appointment_service_id_required(conn)



async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
