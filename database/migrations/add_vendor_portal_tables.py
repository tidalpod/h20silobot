"""Migration: Add vendor portal tables (vendor_verifications, invoices, projects)
and project_id FK to work_orders"""

import asyncio
import os
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)


async def run_migration():
    """Create vendor portal, invoice, and project tables"""
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
            # 1. Create vendor_verifications table
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS vendor_verifications (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER REFERENCES vendors(id) ON DELETE CASCADE,
                    phone VARCHAR(20) NOT NULL,
                    code VARCHAR(6) NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    verified BOOLEAN DEFAULT FALSE,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("Created vendor_verifications table")

            # 2. Create projects table
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    status VARCHAR(20) DEFAULT 'planning',
                    budget NUMERIC(10,2),
                    start_date DATE,
                    end_date DATE,
                    completed_date DATE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("Created projects table")

            # 3. Add project_id column to work_orders (if not exists)
            result = await conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'work_orders' AND column_name = 'project_id'
            """))
            if not result.fetchone():
                await conn.execute(text("""
                    ALTER TABLE work_orders
                    ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL
                """))
                logger.info("Added project_id to work_orders")
            else:
                logger.info("work_orders.project_id already exists")

            # 4. Create invoices table
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS invoices (
                    id SERIAL PRIMARY KEY,
                    vendor_id INTEGER NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    work_order_id INTEGER REFERENCES work_orders(id) ON DELETE SET NULL,
                    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    amount NUMERIC(10,2) NOT NULL,
                    file_url VARCHAR(500),
                    status VARCHAR(20) DEFAULT 'submitted',
                    submitted_at TIMESTAMP DEFAULT NOW(),
                    approved_at TIMESTAMP,
                    paid_at TIMESTAMP,
                    rejected_at TIMESTAMP,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            logger.info("Created invoices table")

            # 5. Create indexes (one per execute call for asyncpg compatibility)
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS ix_vendor_verifications_phone ON vendor_verifications(phone)",
                "CREATE INDEX IF NOT EXISTS ix_projects_property ON projects(property_id)",
                "CREATE INDEX IF NOT EXISTS ix_projects_status ON projects(status)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_vendor ON invoices(vendor_id)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_status ON invoices(status)",
                "CREATE INDEX IF NOT EXISTS ix_invoices_property ON invoices(property_id)",
                "CREATE INDEX IF NOT EXISTS ix_work_orders_project ON work_orders(project_id)",
            ]:
                await conn.execute(text(idx_sql))
            logger.info("Created indexes")

        logger.info("Vendor portal migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
