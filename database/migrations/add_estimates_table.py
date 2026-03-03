"""Migration: Add estimates table for vendor cost estimates"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Create estimates table"""
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
            # 1. Create estimates table
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS estimates (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    amount NUMERIC(10,2) NOT NULL,
                    file_url VARCHAR(500),
                    status VARCHAR(20) DEFAULT 'submitted',
                    submitted_at TIMESTAMP DEFAULT NOW(),
                    approved_at TIMESTAMP,
                    rejected_at TIMESTAMP,
                    notes TEXT,
                    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("Created estimates table")

            # 2. Create indexes
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS ix_estimates_vendor ON estimates(vendor_id)",
                "CREATE INDEX IF NOT EXISTS ix_estimates_status ON estimates(status)",
                "CREATE INDEX IF NOT EXISTS ix_estimates_property ON estimates(property_id)",
                "CREATE INDEX IF NOT EXISTS ix_estimates_project ON estimates(project_id)",
            ]:
                await conn.execute(text(idx_sql))
            logger.info("Created indexes")

        logger.info("Estimates migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
