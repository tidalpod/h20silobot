"""Migration: Add vendor_id column to sms_messages for vendor SMS conversations"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Add vendor_id FK and index to sms_messages table"""
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
            # Check if vendor_id column already exists
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'sms_messages' AND column_name = 'vendor_id'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    ALTER TABLE sms_messages
                    ADD COLUMN vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL
                """))
                logger.info("Added vendor_id to sms_messages")
            else:
                logger.info("sms_messages.vendor_id already exists")

            # Create index
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_sms_messages_vendor ON sms_messages(vendor_id)"
            ))
            logger.info("Created vendor_id index")

        logger.info("Vendor SMS migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
