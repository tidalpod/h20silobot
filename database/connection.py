"""Database connection management"""

import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Global variables
engine = None
AsyncSessionLocal = None


async def init_db():
    """Initialize database - call this once at startup"""
    global engine, AsyncSessionLocal

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from .models import Base

    database_url = os.getenv("DATABASE_URL", "")

    print(f"[DB] DATABASE_URL exists: {bool(database_url)}")
    print(f"[DB] DATABASE_URL length: {len(database_url)}")

    if not database_url:
        print("[DB] ERROR: DATABASE_URL is empty!")
        logger.error("DATABASE_URL is empty!")
        return False

    # Mask and log
    if "@" in database_url:
        host_part = database_url.split("@")[1] if "@" in database_url else ""
        print(f"[DB] Connecting to: ...@{host_part}")

    # Convert to async
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        print("[DB] Creating engine...")
        engine = create_async_engine(
            database_url,
            poolclass=NullPool,
            echo=False,
        )

        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        print("[DB] Testing connection...")
        # Test the connection
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        print("[DB] SUCCESS - Database connected and tables created!")
        logger.info("Database connected successfully")
        return True

    except Exception as e:
        print(f"[DB] FAILED: {e}")
        logger.error(f"Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        engine = None
        AsyncSessionLocal = None
        return False


def is_connected():
    """Check if database is connected"""
    return engine is not None and AsyncSessionLocal is not None


@asynccontextmanager
async def get_session():
    """Context manager for database sessions"""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not connected")

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
