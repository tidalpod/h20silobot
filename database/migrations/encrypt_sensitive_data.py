"""Encrypt legacy vault, Plaid, routing, and bank-account values in place."""

import logging

from sqlalchemy import text

from database.encrypted import decrypt_sensitive_value, encrypt_sensitive_value, is_encrypted


logger = logging.getLogger(__name__)

SENSITIVE_COLUMNS = (
    ("vault_entries", "password"),
    ("tenant_bank_accounts", "plaid_access_token"),
    ("entity_bank_accounts", "plaid_access_token"),
    ("entity_bank_accounts", "routing_number"),
    ("entity_bank_accounts", "account_number"),
)


async def run_migration(engine) -> None:
    """Widen sensitive columns and encrypt every remaining plaintext value."""
    async with engine.begin() as conn:
        for table, column in SENSITIVE_COLUMNS:
            exists = await conn.scalar(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = :table AND column_name = :column
                )
            """), {"table": table, "column": column})
            if not exists:
                continue

            await conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TEXT"))
            rows = (await conn.execute(text(
                f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} <> ''"
            ))).all()
            # Validate that the configured key can decrypt existing ciphertext.
            # This prevents a wrong/rotated key from starting the app in a state
            # where credentials only fail later during live requests.
            for _, value in rows:
                if is_encrypted(value):
                    decrypt_sensitive_value(value)
            updates = [
                {"id": row[0], "value": encrypt_sensitive_value(row[1])}
                for row in rows
                if not is_encrypted(row[1])
            ]
            if updates:
                await conn.execute(
                    text(f"UPDATE {table} SET {column} = :value WHERE id = :id"),
                    updates,
                )
                logger.info("Encrypted %s legacy values in %s.%s", len(updates), table, column)
