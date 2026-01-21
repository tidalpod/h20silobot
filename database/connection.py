"""Database connection management"""

import logging
import os
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from .models import Base

logger = logging.getLogger(__name__)

# Get database URL from environment
database_url = os.getenv("DATABASE_URL", "")

# Log for debugging (mask password)
if database_url:
    masked_url = database_url.split("@")[0][:20] + "...@..." if "@" in database_url else database_url[:30]
    logger.info(f"DATABASE_URL format: {masked_url}")
else:
    logger.error("DATABASE_URL is empty!")

# Convert standard postgres URL to async
if database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = None
AsyncSessionLocal = None

if database_url and "postgresql" in database_url:
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
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
else:
    logger.error(f"Invalid DATABASE_URL: must start with postgresql://")


async def init_db():
    """Initialize database tables"""
    if not engine:
        logger.error("Cannot init_db: engine is None")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")


async def get_db() -> AsyncSession:
    """Get a database session"""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def get_session():
    """Context manager for database sessions"""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not configured")
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
