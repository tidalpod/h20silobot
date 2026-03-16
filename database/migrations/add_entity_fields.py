"""Migration: Add expanded entity fields (EIN, address, billing, formation) and document fields

Run this once:
    python -m database.migrations.add_entity_fields
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


async def run_migration():
    """Add expanded fields to entity_configs and entity_documents tables"""
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
            # --- entity_configs new columns ---
            entity_columns = {
                "entity_type": "VARCHAR(50)",
                "ein": "VARCHAR(20)",
                "address_street": "VARCHAR(255)",
                "address_city": "VARCHAR(100)",
                "address_state": "VARCHAR(2)",
                "address_zip": "VARCHAR(10)",
                "billing_contact_name": "VARCHAR(255)",
                "billing_email": "VARCHAR(255)",
                "billing_phone": "VARCHAR(20)",
                "billing_address_street": "VARCHAR(255)",
                "billing_address_city": "VARCHAR(100)",
                "billing_address_state": "VARCHAR(2)",
                "billing_address_zip": "VARCHAR(10)",
                "state_of_formation": "VARCHAR(2)",
                "formation_date": "DATE",
            }

            for col_name, col_type in entity_columns.items():
                result = await conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'entity_configs' AND column_name = :col
                """), {"col": col_name})
                if result.fetchone():
                    print(f"  Column 'entity_configs.{col_name}' already exists, skipping")
                    continue

                print(f"  Adding 'entity_configs.{col_name}' ({col_type})...")
                await conn.execute(text(
                    f"ALTER TABLE entity_configs ADD COLUMN {col_name} {col_type}"
                ))

            # --- entity_documents new columns ---
            doc_columns = {
                "doc_label": "VARCHAR(100)",
                "expiration_date": "DATE",
                "notes": "TEXT",
            }

            for col_name, col_type in doc_columns.items():
                result = await conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'entity_documents' AND column_name = :col
                """), {"col": col_name})
                if result.fetchone():
                    print(f"  Column 'entity_documents.{col_name}' already exists, skipping")
                    continue

                print(f"  Adding 'entity_documents.{col_name}' ({col_type})...")
                await conn.execute(text(
                    f"ALTER TABLE entity_documents ADD COLUMN {col_name} {col_type}"
                ))

            # Widen doc_type from VARCHAR(20) to VARCHAR(50)
            print("  Widening 'entity_documents.doc_type' to VARCHAR(50)...")
            await conn.execute(text(
                "ALTER TABLE entity_documents ALTER COLUMN doc_type TYPE VARCHAR(50)"
            ))

            print("SUCCESS: All entity fields migration complete")
            return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
