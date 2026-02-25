"""Migration: Add maintenance tables (vendors, work_orders, work_order_photos)

Run this once:
    python -m database.migrations.add_maintenance_tables
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def run_migration():
    """Create maintenance tables"""
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
            # Check if vendors table exists
            result = await conn.execute(text("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name = 'vendors'
            """))
            if result.fetchone():
                print("Maintenance tables already exist")
                return True

            # Create vendors table
            print("Creating vendors table...")
            await conn.execute(text("""
                CREATE TABLE vendors (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    phone VARCHAR(20),
                    email VARCHAR(255),
                    specialty VARCHAR(100),
                    company VARCHAR(255),
                    notes TEXT,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))

            # Create work_orders table
            print("Creating work_orders table...")
            await conn.execute(text("""
                CREATE TABLE work_orders (
                    id SERIAL PRIMARY KEY,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    tenant_id INTEGER REFERENCES tenants(id) ON DELETE SET NULL,
                    vendor_id INTEGER REFERENCES vendors(id) ON DELETE SET NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT,
                    category VARCHAR(20) DEFAULT 'general',
                    priority VARCHAR(20) DEFAULT 'normal',
                    status VARCHAR(20) DEFAULT 'new',
                    unit_area VARCHAR(100),
                    scheduled_date DATE,
                    completed_date DATE,
                    estimated_cost NUMERIC(10,2),
                    actual_cost NUMERIC(10,2),
                    resolution_notes TEXT,
                    submitted_by_tenant BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            await conn.execute(text("CREATE INDEX ix_work_orders_status ON work_orders(status)"))
            await conn.execute(text("CREATE INDEX ix_work_orders_property ON work_orders(property_id)"))
            await conn.execute(text("CREATE INDEX ix_work_orders_priority ON work_orders(priority)"))

            # Create work_order_photos table
            print("Creating work_order_photos table...")
            await conn.execute(text("""
                CREATE TABLE work_order_photos (
                    id SERIAL PRIMARY KEY,
                    work_order_id INTEGER NOT NULL REFERENCES work_orders(id) ON DELETE CASCADE,
                    url VARCHAR(500) NOT NULL,
                    caption VARCHAR(255),
                    uploaded_by_tenant BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))

            print("SUCCESS: Maintenance tables created")
            return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
