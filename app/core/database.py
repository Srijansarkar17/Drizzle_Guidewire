"""
Async Database Engine + Session Factory (SQLAlchemy 2.0 async).
Supports both PostgreSQL (asyncpg) and SQLite (aiosqlite) backends.
"""

import logging
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = logging.getLogger("drizzle.db")

# ── Engine ────────────────────────────────────────────────────────
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if _is_sqlite:
    # SQLite doesn't support connection pooling options
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL with full pooling
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )

# ── Session factory ──────────────────────────────────────────────
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base class for all ORM models ────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Dependency for FastAPI ───────────────────────────────────────
async def get_db() -> AsyncSession:
    """Yield a transactional async session, auto-close on exit."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Lifecycle helpers ────────────────────────────────────────────
async def init_db():
    """Create all tables from ORM metadata (dev convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables ensured.")


async def close_db():
    """Dispose engine pool."""
    await engine.dispose()
    log.info("Database connection pool closed.")
