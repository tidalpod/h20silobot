"""Migration: Create vault_entries and vault_pin tables for the Blue Deer bot password vault"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Create vault_entries and vault_pin tables if they don't exist"""
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
                WHERE table_name = 'vault_entries'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE vault_entries (
                        id SERIAL PRIMARY KEY,
                        label VARCHAR(120) NOT NULL,
                        username VARCHAR(255),
                        password_encrypted TEXT NOT NULL,
                        notes TEXT,
                        created_at TIMESTAMP DEFAULT NOW(),
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                logger.info("Created vault_entries table")
            else:
                logger.info("vault_entries table already exists")

            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'vault_pin'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE vault_pin (
                        id SERIAL PRIMARY KEY,
                        pin_hash VARCHAR(255) NOT NULL,
                        failed_attempts INTEGER DEFAULT 0 NOT NULL,
                        locked_until TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """))
                logger.info("Created vault_pin table")
            else:
                logger.info("vault_pin table already exists")

            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'vault_access_log'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    CREATE TABLE vault_access_log (
                        id SERIAL PRIMARY KEY,
                        telegram_user_id BIGINT NOT NULL,
                        action VARCHAR(20) NOT NULL,
                        entry_id INTEGER,
                        entry_label VARCHAR(120),
                        at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
                await conn.execute(text("""
                    CREATE INDEX ix_vault_access_log_at ON vault_access_log (at)
                """))
                await conn.execute(text("""
                    CREATE INDEX ix_vault_access_log_user ON vault_access_log (telegram_user_id)
                """))
                logger.info("Created vault_access_log table")
            else:
                logger.info("vault_access_log table already exists")

        logger.info("Vault migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Vault migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
