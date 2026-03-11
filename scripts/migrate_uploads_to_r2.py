#!/usr/bin/env python3
"""One-time migration: upload all local files to R2 and update DB URLs.

Usage:
    python scripts/migrate_uploads_to_r2.py [--dry-run]

Requirements:
    - R2 env vars must be set (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, etc.)
    - Database must be accessible
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def migrate(dry_run: bool = False):
    from database.connection import init_db, get_session
    from webapp.services.storage_service import storage, UPLOAD_BASE

    if not storage.using_r2:
        logger.error("R2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                      "R2_ACCESS_KEY_SECRET, R2_BUCKET_NAME, R2_PUBLIC_URL env vars.")
        return

    await init_db()

    upload_base = Path(UPLOAD_BASE)
    if not upload_base.exists():
        logger.error(f"Upload directory not found: {upload_base}")
        return

    # Collect all files
    all_files = []
    for f in upload_base.rglob("*"):
        if f.is_file():
            key = str(f.relative_to(upload_base))
            all_files.append((key, f))

    logger.info(f"Found {len(all_files)} files to migrate")

    # Upload each file to R2
    uploaded = 0
    failed = 0
    for key, filepath in all_files:
        if dry_run:
            logger.info(f"[DRY RUN] Would upload: {key} ({filepath.stat().st_size:,} bytes)")
            uploaded += 1
            continue

        try:
            import mimetypes
            content_type = mimetypes.guess_type(str(filepath))[0] or "application/octet-stream"
            url = storage.upload_from_path(key, str(filepath), content_type)
            logger.info(f"Uploaded: {key} -> {url}")
            uploaded += 1
        except Exception as e:
            logger.error(f"Failed to upload {key}: {e}")
            failed += 1

    logger.info(f"Upload complete: {uploaded} uploaded, {failed} failed")

    if dry_run:
        logger.info("[DRY RUN] No database updates made")
        return

    # Update DB URLs from /uploads/... to full R2 URLs
    logger.info("Updating database URLs...")
    await _update_db_urls(storage)
    logger.info("Migration complete!")


async def _update_db_urls(storage):
    """Update all /uploads/... URLs in the database to full R2 URLs."""
    from database.connection import get_session
    from sqlalchemy import select

    # All models with file URL columns
    url_columns = [
        ("database.models", "PropertyPhoto", "url"),
        ("database.models", "Property", "featured_photo_url"),
        ("database.models", "WorkOrderPhoto", "url"),
        ("database.models", "WorkOrder", "payment_receipt_url"),
        ("database.models", "Invoice", "file_url"),
        ("database.models", "LeaseDocument", "file_url"),
        ("database.models", "ProjectDocument", "file_url"),
        ("database.models", "ProjectDraw", "receipt_url"),
        ("database.models", "InspectionViolation", "file_url"),
        ("database.models", "InspectionViolation", "image_url"),
        ("database.models", "ESignSigner", "signature_file_url"),
        ("database.models", "ESignEnvelope", "signed_file_url"),
    ]

    import importlib

    async with get_session() as session:
        total_updated = 0
        for module_path, model_name, column_name in url_columns:
            try:
                module = importlib.import_module(module_path)
                model = getattr(module, model_name)
                col = getattr(model, column_name)

                result = await session.execute(
                    select(model).where(col.isnot(None), col.like("/uploads/%"))
                )
                records = result.scalars().all()

                for record in records:
                    old_url = getattr(record, column_name)
                    if old_url and old_url.startswith("/uploads/"):
                        key = old_url.removeprefix("/uploads/")
                        new_url = storage.url(key)
                        setattr(record, column_name, new_url)
                        total_updated += 1

                if records:
                    logger.info(f"  {model_name}.{column_name}: updated {len(records)} records")
            except Exception as e:
                logger.warning(f"  {model_name}.{column_name}: skipped ({e})")

        logger.info(f"Total DB records updated: {total_updated}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("Running in DRY RUN mode — no changes will be made")
    asyncio.run(migrate(dry_run=dry_run))
