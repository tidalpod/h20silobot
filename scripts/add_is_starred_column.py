#!/usr/bin/env python3
"""Add is_starred column to property_photos table"""

import asyncio
import sys
sys.path.insert(0, '.')

from database import connection


async def main():
    print("Adding is_starred column to property_photos table...")

    await connection.init_db()

    async with connection.engine.connect() as conn:
        # Check if column already exists
        from sqlalchemy import text

        result = await conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'property_photos'
            AND column_name = 'is_starred'
        """))

        exists = result.fetchone()

        if exists:
            print("Column 'is_starred' already exists. No changes needed.")
            return

        # Add the column
        await conn.execute(text("""
            ALTER TABLE property_photos
            ADD COLUMN is_starred BOOLEAN DEFAULT FALSE
        """))
        await conn.commit()

        print("Successfully added 'is_starred' column to property_photos table!")


if __name__ == "__main__":
    asyncio.run(main())
