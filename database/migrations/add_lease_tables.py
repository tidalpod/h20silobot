"""Migration: Add lease_documents table

Run this once:
    python -m database.migrations.add_lease_tables
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def run_migration():
    """Create lease_documents table"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'lease_documents'
            """))
            if result.fetchone():
                print("lease_documents table already exists")
                return True

            print("Creating lease_documents table...")
            await conn.execute(text("""
                CREATE TABLE lease_documents (
                    id SERIAL PRIMARY KEY,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
                    title VARCHAR(255) NOT NULL,
                    file_url VARCHAR(500) NOT NULL,
                    file_type VARCHAR(20),
                    file_size INTEGER,
                    lease_start DATE,
                    lease_end DATE,
                    monthly_rent NUMERIC(10,2),
                    status VARCHAR(20) DEFAULT 'active',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            await conn.execute(text("CREATE INDEX ix_lease_documents_status ON lease_documents(status)"))
            await conn.execute(text("CREATE INDEX ix_lease_documents_property ON lease_documents(property_id)"))

            print("SUCCESS: lease_documents table created")
            return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
