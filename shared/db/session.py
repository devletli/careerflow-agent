from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
import logging

from shared.config import settings

logger = logging.getLogger(__name__)

# Ensure postgresql+asyncpg driver URL format
db_url = settings.DATABASE_URL
if db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

async_engine = create_async_engine(
    db_url,
    echo=False,
    future=True,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session_maker = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db_health() -> bool:
    """Checks PostgreSQL connectivity with SELECT 1."""
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            return result.scalar() == 1
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return False
