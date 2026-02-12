"""Migration: Add entity column to properties table

Run this once to add the entity column:
    python -m database.migrations.add_entity_column
"""

import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def run_migration():
    """Add entity column to properties table"""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        print("ERROR: DATABASE_URL not set")
        return False

    # Convert to async
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            # Check if column exists
            result = await conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'properties' AND column_name = 'entity'
            """))
            exists = result.fetchone()

            if exists:
                print("Column 'entity' already exists in properties table")
                return True

            # Add the column
            print("Adding 'entity' column to properties table...")
            await conn.execute(text("""
                ALTER TABLE properties
                ADD COLUMN entity VARCHAR(100)
            """))
            print("SUCCESS: Column 'entity' added to properties table")
            return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
