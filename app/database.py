from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "sqlite+aiosqlite:///./dental_agent.db"

engine = create_async_engine(DATABASE_URL, echo=True)

SessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)



async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session