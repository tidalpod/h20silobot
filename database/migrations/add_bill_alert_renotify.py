"""Migration: Add renotify_increment to bill_alert_settings and notified_amount to bill_alert_log"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Add columns for re-notification increment tracking"""
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
            # Add renotify_increment to bill_alert_settings
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'bill_alert_settings' AND column_name = 'renotify_increment'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    ALTER TABLE bill_alert_settings
                    ADD COLUMN renotify_increment NUMERIC(10,2) NOT NULL DEFAULT 50
                """))
                logger.info("Added renotify_increment column to bill_alert_settings")
            else:
                logger.info("renotify_increment column already exists")

            # Add notified_amount to bill_alert_log
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'bill_alert_log' AND column_name = 'notified_amount'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    ALTER TABLE bill_alert_log
                    ADD COLUMN notified_amount NUMERIC(10,2)
                """))
                logger.info("Added notified_amount column to bill_alert_log")
            else:
                logger.info("notified_amount column already exists")

        logger.info("Bill alert renotify migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Bill alert renotify migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
