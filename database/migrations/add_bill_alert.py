"""Migration: Create bill_alert_settings and bill_alert_log tables"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Create bill alert tables if they don't exist"""
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
            # Create bill_alert_settings table
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'bill_alert_settings'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE bill_alert_settings (
                        id SERIAL PRIMARY KEY,
                        enabled BOOLEAN NOT NULL DEFAULT FALSE,
                        threshold_amount NUMERIC(10,2) NOT NULL DEFAULT 200,
                        notify_sms BOOLEAN NOT NULL DEFAULT TRUE,
                        notify_email BOOLEAN NOT NULL DEFAULT FALSE,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                logger.info("Created bill_alert_settings table")
            else:
                logger.info("bill_alert_settings table already exists")

            # Create bill_alert_log table
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'bill_alert_log'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE bill_alert_log (
                        id SERIAL PRIMARY KEY,
                        property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                        bill_id INTEGER NOT NULL REFERENCES water_bills(id) ON DELETE CASCADE,
                        sent_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                await conn.execute(text("""
                    CREATE UNIQUE INDEX ix_bill_alert_log_unique
                    ON bill_alert_log (property_id, bill_id)
                """))
                logger.info("Created bill_alert_log table")
            else:
                logger.info("bill_alert_log table already exists")

        logger.info("Bill alert migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Bill alert migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
