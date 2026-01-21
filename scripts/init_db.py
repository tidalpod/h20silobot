#!/usr/bin/env python3
"""Initialize the database tables"""

import asyncio
import sys
sys.path.insert(0, '.')

from database.connection import init_db, engine
from database.models import Base


async def main():
    print("Initializing database...")
    await init_db()
    print("Database tables created successfully!")

    # List tables
    async with engine.connect() as conn:
        from sqlalchemy import inspect
        def get_tables(connection):
            inspector = inspect(connection)
            return inspector.get_table_names()

        tables = await conn.run_sync(get_tables)
        print(f"\nCreated tables: {', '.join(tables)}")


if __name__ == "__main__":
    asyncio.run(main())
