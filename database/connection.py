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
        # Investment / Financial columns on properties
        ("properties", "purchase_price", "NUMERIC(12,2)"),
        ("properties", "purchase_date", "DATE"),
        ("properties", "appraised_value", "NUMERIC(12,2)"),
        ("properties", "appraisal_date", "DATE"),
        ("properties", "loan_amount", "NUMERIC(12,2)"),
        ("properties", "loan_balance", "NUMERIC(12,2)"),
        ("properties", "interest_rate", "NUMERIC(5,3)"),
        ("properties", "loan_term_years", "INTEGER"),
        ("properties", "loan_start_date", "DATE"),
        ("properties", "monthly_pi", "NUMERIC(10,2)"),
        ("properties", "monthly_tax", "NUMERIC(10,2)"),
        ("properties", "monthly_insurance", "NUMERIC(10,2)"),
        ("properties", "monthly_piti", "NUMERIC(10,2)"),
        ("properties", "hoa_monthly", "NUMERIC(10,2)"),
        ("properties", "rehab_cost", "NUMERIC(12,2)"),
        # Work order payment tracking
        ("work_orders", "is_paid", "BOOLEAN DEFAULT false"),
        ("work_orders", "paid_date", "DATE"),
        ("work_orders", "payment_method", "VARCHAR(50)"),
        ("work_orders", "payment_notes", "TEXT"),
        ("work_orders", "payment_receipt_url", "VARCHAR(500)"),
        # In-house e-signing columns on existing esign_envelopes
        ("esign_envelopes", "signing_mode", "VARCHAR(20) DEFAULT 'inhouse'"),
        ("esign_envelopes", "void_reason", "VARCHAR(500)"),
        # Sequential signing order
        ("esign_signers", "signing_order", "INTEGER DEFAULT 1"),
        # Extended tenant application fields
        ("tenant_applications", "applicant_dob", "DATE"),
        ("tenant_applications", "applicant_type", "VARCHAR(20) DEFAULT 'tenant'"),
        ("tenant_applications", "application_data", "TEXT"),
        # Stripe payment for application fee
        ("tenant_applications", "stripe_checkout_session_id", "VARCHAR(255)"),
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

    # Add 'pending_payment' to applicationstatus enum (must run outside a transaction)
    try:
        from sqlalchemy.pool import NullPool
        raw_url = os.getenv("DATABASE_URL", "")
        if raw_url.startswith("postgresql://"):
            raw_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        from sqlalchemy.ext.asyncio import create_async_engine as _cae
        _tmp = _cae(raw_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with _tmp.connect() as conn:
            await conn.execute(text(
                "ALTER TYPE applicationstatus ADD VALUE IF NOT EXISTS 'pending_payment' BEFORE 'pending'"
            ))
        await _tmp.dispose()
    except Exception:
        pass  # Value already exists or enum doesn't exist yet

    # Convert showings.status from native enum to VARCHAR (allows adding new values without ALTER TYPE)
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "ALTER TABLE showings ALTER COLUMN status TYPE VARCHAR(20) USING status::text"
            ))
            print("[DB] Converted showings.status from enum to VARCHAR(20)")
        except Exception as e:
            pass  # Already converted or column doesn't exist

    # Normalize showings.status to lowercase (old enum stored as UPPERCASE)
    async with engine.begin() as conn:
        try:
            await conn.execute(text(
                "UPDATE showings SET status = LOWER(status) WHERE status != LOWER(status)"
            ))
        except Exception:
            pass

async def _seed_lease_default_terms(engine):
    """Seed the default Tenant Responsibilities Addendum if the table is empty."""
    default_content = """TENANT RESPONSIBILITIES ADDENDUM

This Tenant Responsibilities Addendum is incorporated into and made part of the lease agreement between Landlord and Tenant for the premises identified in the lease.

Tenant agrees to the following conditions:

TENANT-CAUSED MAINTENANCE & REPAIRS

1. Plumbing & Drain Issues
Tenant shall be responsible for maintaining clear and functional drains, toilets, and garbage disposals. Any clogs or damage caused by tenant negligence, including but not limited to flushing wipes, grease, food, hair buildup, or other non-flushable items, shall be repaired at the tenant's expense. Landlord shall be responsible for major plumbing issues not caused by tenant misuse, such as broken pipes due to age or structural failure.

2. HVAC & Air Filters
Tenant shall replace HVAC filters every one to three months to ensure proper system function. If failure to replace filters results in HVAC system damage (e.g., burnt-out motor, excessive wear), the tenant shall be liable for all repair or replacement costs.

3. Pest Control
Tenant shall maintain a clean living environment free from food waste, trash buildup, and standing water to prevent pest infestations. Landlord shall be responsible for structural pest issues, including pre-existing infestations or those caused by defects in the property (e.g., termites). If an infestation occurs due to tenant negligence, the tenant shall be responsible for all necessary extermination and remediation costs.

4. Mold & Moisture Prevention
Tenant shall report any water leaks, plumbing issues, or excessive moisture to the landlord immediately. Tenant shall use exhaust fans in bathrooms and kitchens, wipe down wet surfaces, and keep the premises adequately ventilated to prevent mold growth. If mold develops due to tenant neglect, such as failure to report leaks or properly ventilate areas, the tenant shall be responsible for all cleaning and remediation costs.

5. Appliance Use & Damage
Tenant shall operate all appliances properly and in accordance with manufacturer guidelines. Any damage resulting from improper use, such as overloading washing machines, inserting metal into microwaves, or misuse of the garbage disposal, shall be repaired at the tenant's expense. Landlord is responsible for appliance malfunctions due to normal wear and tear.

PROPERTY CARE & DAMAGE RESPONSIBILITY

6. Window, Screen, and Door Damage
Tenant shall be responsible for replacing or repairing any broken windows, damaged screens, or door hardware, including locks and knobs, unless the damage is due to a documented break-in with a police report.

7. Flooring and Carpet Maintenance
Tenant shall keep all flooring clean and free from stains, burns, and excessive wear. Any damage beyond normal wear and tear, including pet-related damage such as scratches, chewing, or urine stains, shall be repaired at the tenant's expense.

8. Light Bulbs and Batteries
Tenant shall replace all light bulbs and smoke detector batteries as needed. Landlord shall be responsible for replacing bulbs or batteries that require special equipment or professional installation.

9. Lawn Care
The tenant is responsible for lawn maintenance, including mowing, trimming bushes, and keeping weeds under control. Failure to maintain the lawn may result in the landlord hiring a service at the tenant's expense.

10. Unauthorized Alterations and Repairs
Tenant shall not make any modifications, repairs, or alterations to the property including but not limited to painting, installing fixtures, or replacing hardware, without prior written consent from the landlord. Any unauthorized changes must be removed or restored to the original condition at the tenant's expense.

11. Smoking and Fire Hazard Prevention
The lease designates the property as non-smoking, the tenant shall not smoke inside the unit. Any costs associated with odor removal, burn marks, or deep cleaning due to smoking shall be charged to the tenant.

12. Utilities - Water Bill Payment Requirement
Tenant acknowledges that payment of the monthly water bill is a material condition of this lease and addendum, regardless of whether the bill is issued directly to the Tenant or reimbursed to the Landlord. Tenant agrees to pay the full water bill balance each month by the due date stated on the bill or as otherwise directed by the Landlord. Failure to pay the water bill in full shall constitute a material breach of the lease and this Addendum. In the event of nonpayment, the Landlord may issue a written notice of default and, if the balance remains unpaid after any applicable cure period required by law, the Landlord may pursue all remedies allowed under the lease and applicable state and local law, including but not limited to termination of tenancy and eviction proceedings. Any unpaid water charges may also be deemed additional rent to the extent permitted by law. This provision shall be enforced in compliance with all applicable HUD, Housing Choice Voucher (HCV), and state landlord-tenant regulations."""

    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT id FROM lease_default_terms LIMIT 1"
        ))
        if not result.fetchone():
            await conn.execute(text(
                "INSERT INTO lease_default_terms (title, content, is_active) "
                "VALUES (:title, :content, true)"
            ), {"title": "Tenant Responsibilities Addendum", "content": default_content})
            print("[DB] Seeded default lease terms (Tenant Responsibilities Addendum)")


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

        # Seed default lease addendum terms
        await _seed_lease_default_terms(engine)

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
