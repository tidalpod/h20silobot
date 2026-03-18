"""Migration: Create inspection_reminder_settings and inspection_reminder_log tables"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Create inspection reminder tables if they don't exist"""
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
            # Create inspection_reminder_settings table
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'inspection_reminder_settings'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE inspection_reminder_settings (
                        id SERIAL PRIMARY KEY,
                        remind_tenant BOOLEAN NOT NULL DEFAULT TRUE,
                        remind_vendor BOOLEAN NOT NULL DEFAULT FALSE,
                        lead_time_minutes INTEGER NOT NULL DEFAULT 120,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                logger.info("Created inspection_reminder_settings table")
            else:
                logger.info("inspection_reminder_settings table already exists")

            # Create inspection_reminder_log table
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'inspection_reminder_log'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE inspection_reminder_log (
                        id SERIAL PRIMARY KEY,
                        property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                        inspection_type VARCHAR(30) NOT NULL,
                        inspection_date DATE NOT NULL,
                        sent_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                await conn.execute(text("""
                    CREATE UNIQUE INDEX ix_insp_reminder_log_unique
                    ON inspection_reminder_log (property_id, inspection_type, inspection_date)
                """))
                logger.info("Created inspection_reminder_log table")
            else:
                logger.info("inspection_reminder_log table already exists")

        logger.info("Inspection reminder migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Inspection reminder migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
