"""Database connection management"""

import logging
import os
from contextlib import asynccontextmanager
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def run_migrations(engine):
    """Run pending migrations to add new columns"""
    migrations = [
        # (table, column, type)
        ("properties", "entity", "VARCHAR(100)"),
        # CO inspection pass/fail status columns
        ("properties", "co_mechanical_status", "VARCHAR(20)"),
        ("properties", "co_electrical_status", "VARCHAR(20)"),
        ("properties", "co_plumbing_status", "VARCHAR(20)"),
        ("properties", "co_zoning_status", "VARCHAR(20)"),
        ("properties", "co_building_status", "VARCHAR(20)"),
        # Inspection violation image support
        ("inspection_violations", "image_url", "VARCHAR(500)"),
        # Rental inspection pass/fail status
        ("properties", "rental_inspection_status", "VARCHAR(20)"),
        # Vendor SMS conversations
        ("sms_messages", "vendor_id", "INTEGER REFERENCES vendors(id) ON DELETE SET NULL"),
        # Entity bank account manual entry fields
        ("entity_bank_accounts", "routing_number", "VARCHAR(9)"),
        ("entity_bank_accounts", "account_number", "VARCHAR(17)"),
        ("entity_bank_accounts", "is_manual", "BOOLEAN DEFAULT false"),
        # Entity bank account on rent payments
        ("rent_payments", "entity_bank_account_id", "INTEGER REFERENCES entity_bank_accounts(id) ON DELETE SET NULL"),
    ]

    async with engine.begin() as conn:
        for table, column, col_type in migrations:
            result = await conn.execute(text(f"""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = '{table}' AND column_name = '{column}'
            """))
            exists = result.fetchone()

            if not exists:
                print(f"[DB] Adding column '{column}' to '{table}'...")
                await conn.execute(text(f"""
                    ALTER TABLE {table}
                    ADD COLUMN {column} {col_type}
                """))
                print(f"[DB] Column '{column}' added successfully")

        # Create indexes for new columns (idempotent)
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sms_messages_vendor ON sms_messages(vendor_id)"
        ))

        # Make Plaid columns nullable on entity_bank_accounts (for manual entries)
        for col in ["plaid_access_token", "plaid_item_id", "plaid_account_id"]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE entity_bank_accounts ALTER COLUMN {col} DROP NOT NULL"
                ))
            except Exception:
                pass  # Column may already be nullable or table may not exist yet

async def _seed_telegram_admins(engine):
    """Ensure default Telegram admin users exist for Blue Deer alerts"""
    admin_users = [
        # (telegram_id, first_name)
        (2092822589, "Admin"),
    ]

    async with engine.begin() as conn:
        for telegram_id, first_name in admin_users:
            result = await conn.execute(text(
                f"SELECT id FROM telegram_users WHERE telegram_id = {telegram_id}"
            ))
            if not result.fetchone():
                await conn.execute(text(
                    f"INSERT INTO telegram_users (telegram_id, first_name, is_admin, notifications_enabled) "
                    f"VALUES ({telegram_id}, '{first_name}', true, true)"
                ))
                print(f"[DB] Added Telegram admin user {telegram_id}")


# Global variables
engine = None
AsyncSessionLocal = None


async def init_db():
    """Initialize database - call this once at startup"""
    global engine, AsyncSessionLocal

    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from .models import Base

    database_url = os.getenv("DATABASE_URL", "")

    print(f"[DB] DATABASE_URL exists: {bool(database_url)}")
    print(f"[DB] DATABASE_URL length: {len(database_url)}")

    if not database_url:
        print("[DB] ERROR: DATABASE_URL is empty!")
        logger.error("DATABASE_URL is empty!")
        return False

    # Mask and log
    if "@" in database_url:
        host_part = database_url.split("@")[1] if "@" in database_url else ""
        print(f"[DB] Connecting to: ...@{host_part}")

    # Convert to async
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    try:
        print("[DB] Creating engine...")
        engine = create_async_engine(
            database_url,
            poolclass=NullPool,
            echo=False,
        )

        AsyncSessionLocal = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        print("[DB] Testing connection...")
        # Test the connection and create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Run migrations for new columns
        await run_migrations(engine)

        # Seed default Telegram admin user for Blue Deer alerts
        await _seed_telegram_admins(engine)

        print("[DB] SUCCESS - Database connected and tables created!")
        logger.info("Database connected successfully")
        return True

    except Exception as e:
        print(f"[DB] FAILED: {e}")
        logger.error(f"Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        engine = None
        AsyncSessionLocal = None
        return False


def is_connected():
    """Check if database is connected"""
    return engine is not None and AsyncSessionLocal is not None


@asynccontextmanager
async def get_session():
    """Context manager for database sessions"""
    if not AsyncSessionLocal:
        raise RuntimeError("Database not connected")

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
