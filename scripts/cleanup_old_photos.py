"""
Script to clean up old photo records with broken URLs.
Run this once after setting up Railway volume.
"""

import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, delete
from database.connection import get_session, init_db
from database.models import PropertyPhoto, Property


async def cleanup_old_photos():
    """Delete photo records with old /static/uploads/ URLs"""

    await init_db()

    async with get_session() as session:
        # Find all photos with old URL pattern
        result = await session.execute(
            select(PropertyPhoto).where(
                PropertyPhoto.url.like("/static/uploads/%")
            )
        )
        old_photos = result.scalars().all()

        if not old_photos:
            print("No old photo records found. Nothing to clean up.")
            return

        print(f"Found {len(old_photos)} photo records with old URLs:")
        for photo in old_photos:
            print(f"  - ID {photo.id}: {photo.url} (property_id: {photo.property_id})")

        # Delete them
        await session.execute(
            delete(PropertyPhoto).where(
                PropertyPhoto.url.like("/static/uploads/%")
            )
        )

        # Also clear featured_photo_url on properties with old URLs
        result = await session.execute(
            select(Property).where(
                Property.featured_photo_url.like("/static/uploads/%")
            )
        )
        properties = result.scalars().all()

        for prop in properties:
            print(f"  - Clearing featured photo for property {prop.id}: {prop.address}")
            prop.featured_photo_url = None

        await session.commit()

        print(f"\nDeleted {len(old_photos)} old photo records.")
        print(f"Cleared featured photo for {len(properties)} properties.")
        print("\nYou can now re-upload photos through the web interface.")


if __name__ == "__main__":
    asyncio.run(cleanup_old_photos())
