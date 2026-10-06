"""Replace legacy public R2 links with application-proxied delivery URLs."""

import logging
import os

from sqlalchemy import text

from webapp.services.storage_service import PROTECTED_PREFIXES


logger = logging.getLogger(__name__)

URL_COLUMNS = (
    ("properties", "featured_photo_url"),
    ("property_photos", "url"),
    ("inspection_violations", "file_url"),
    ("inspection_violations", "image_url"),
    ("co_inspection_documents", "file_url"),
    ("co_inspection_documents", "image_url"),
    ("lease_documents", "file_url"),
    ("work_orders", "payment_receipt_url"),
    ("work_order_photos", "url"),
    ("invoices", "file_url"),
    ("project_documents", "file_url"),
    ("project_draws", "receipt_url"),
    ("entity_documents", "file_url"),
    ("landlord_packets", "file_url"),
    ("esign_envelopes", "signed_file_url"),
    ("esign_signers", "signature_file_url"),
)


async def run_migration(engine) -> None:
    public_url = os.getenv("R2_PUBLIC_URL", "").rstrip("/")
    if not public_url:
        return
    prefix = f"{public_url}/"

    async with engine.begin() as conn:
        for table, column in URL_COLUMNS:
            exists = await conn.scalar(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = :table AND column_name = :column
                )
            """), {"table": table, "column": column})
            if not exists:
                continue
            rows = (await conn.execute(
                text(f"SELECT id, {column} FROM {table} WHERE {column} LIKE :prefix"),
                {"prefix": f"{prefix}%"},
            )).all()
            for row_id, old_url in rows:
                key = old_url[len(prefix):]
                route = "/protected-files/" if key.startswith(PROTECTED_PREFIXES) else "/media-files/"
                await conn.execute(
                    text(f"UPDATE {table} SET {column} = :url WHERE id = :id"),
                    {"url": f"{route}{key}", "id": row_id},
                )
            if rows:
                logger.info("Migrated %s legacy storage URLs in %s.%s", len(rows), table, column)
