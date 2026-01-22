"""Database connection management"""

import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Lazy initialization - don't connect at import time
engine = None
AsyncSessionLocal = None
_initialized = False


def _init_engine():
    """Initialize database engine lazily"""
    global engine, AsyncSessionLocal, _initialized

    if _initialized:
        return engine is not None

    _initialized = True

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool

    database_url = os.getenv("DATABASE_URL", "")

    logger.info(f"DATABASE_URL length: {len(database_url)}")

    if not database_url:
        logger.error("DATABASE_URL is empty!")
        return False

    # Log masked URL for debugging
    if "@" in database_url:
        parts = database_url.split("@")
        masked = parts[0][:15] + "***@" + parts[1]
        logger.info(f"DATABASE_URL: {masked}")

    # Convert to async driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        logger.info("Converted to asyncpg driver")

    try:
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
        logger.info("Database engine created successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def get_engine():
    """Get the database engine, initializing if needed"""
    _init_engine()
    return engine


async def init_db():
    """Initialize database tables"""
    _init_engine()  # Ensure engine is initialized

    if not engine:
        logger.error("Cannot init_db: engine is None")
        return False

    from .models import Base

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to init database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


@asynccontextmanager
async def get_session():
    """Context manager for database sessions"""
    _init_engine()  # Ensure engine is initialized

    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured - AsyncSessionLocal is None")

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
