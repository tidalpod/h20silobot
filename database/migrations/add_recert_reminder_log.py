"""Migration: Create recert_reminder_log table for milestone-based recert reminders"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Create recert_reminder_log table if it doesn't exist"""
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL not set")
        return False

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'recert_reminder_log'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE recert_reminder_log (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                        recert_date DATE NOT NULL,
                        milestone INTEGER NOT NULL,
                        sent_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                await conn.execute(text("""
                    CREATE UNIQUE INDEX ix_recert_reminder_log_unique
                    ON recert_reminder_log (tenant_id, recert_date, milestone)
                """))
                logger.info("Created recert_reminder_log table")
            else:
                logger.info("recert_reminder_log table already exists")

        logger.info("Recert reminder migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Recert reminder migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
