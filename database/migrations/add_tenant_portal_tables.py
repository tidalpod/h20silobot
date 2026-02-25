"""Migration: Add tenant_verifications table

Run this once:
    python -m database.migrations.add_tenant_portal_tables
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def run_migration():
    """Create tenant_verifications table"""
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
                WHERE table_name = 'tenant_verifications'
            """))
            if result.fetchone():
                print("tenant_verifications table already exists")
                return True

            print("Creating tenant_verifications table...")
            await conn.execute(text("""
                CREATE TABLE tenant_verifications (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
                    phone VARCHAR(20) NOT NULL,
                    code VARCHAR(6) NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    verified BOOLEAN DEFAULT FALSE,
                    attempts INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))

            print("SUCCESS: tenant_verifications table created")
            return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
