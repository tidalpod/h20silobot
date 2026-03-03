"""Migration: Add reminder_sent_at to showings + phone to web_users"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Add reminder_sent_at column to showings table"""
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL not set")
        return False

    # Handle Railway's postgres:// vs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            # Check if column already exists
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'showings' AND column_name = 'reminder_sent_at'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    ALTER TABLE showings
                    ADD COLUMN reminder_sent_at TIMESTAMP NULL
                """))
                logger.info("Added reminder_sent_at to showings")
            else:
                logger.info("showings.reminder_sent_at already exists")

            # Add phone column to web_users
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'web_users' AND column_name = 'phone'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    ALTER TABLE web_users
                    ADD COLUMN phone VARCHAR(20) NULL
                """))
                logger.info("Added phone to web_users")
            else:
                logger.info("web_users.phone already exists")

        logger.info("Migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
