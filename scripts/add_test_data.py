#!/usr/bin/env python3
"""Add test data for development"""

import asyncio
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, '.')

from database.connection import get_session, init_db
from database.models import Property, WaterBill, BillStatus


async def main():
    await init_db()

    async with get_session() as session:
        # Create test properties
        props = [
            Property(
                address="123 Main St, Detroit MI",
                bsa_account_number="ACC001234",
                owner_name="Test Owner 1"
            ),
            Property(
                address="456 Oak Ave, Detroit MI",
                bsa_account_number="ACC005678",
                owner_name="Test Owner 2"
            ),
            Property(
                address="789 Pine Rd, Detroit MI",
                bsa_account_number="ACC009012",
                owner_name="Test Owner 3"
            ),
        ]

        for prop in props:
            session.add(prop)

        await session.flush()

        # Add bills with different statuses
        bills = [
            # Current bill
            WaterBill(
                property_id=props[0].id,
                amount_due=Decimal("125.50"),
                due_date=date.today() + timedelta(days=20),
                statement_date=date.today() - timedelta(days=10),
                previous_balance=Decimal("0"),
                current_charges=Decimal("125.50"),
                status=BillStatus.CURRENT,
                water_usage_gallons=4500
            ),
            # Due soon
            WaterBill(
                property_id=props[1].id,
                amount_due=Decimal("89.75"),
                due_date=date.today() + timedelta(days=5),
                statement_date=date.today() - timedelta(days=25),
                previous_balance=Decimal("0"),
                current_charges=Decimal("89.75"),
                status=BillStatus.DUE_SOON,
                water_usage_gallons=3200
            ),
            # Overdue
            WaterBill(
                property_id=props[2].id,
                amount_due=Decimal("215.00"),
                due_date=date.today() - timedelta(days=10),
                statement_date=date.today() - timedelta(days=40),
                previous_balance=Decimal("175.00"),
                current_charges=Decimal("40.00"),
                late_fees=Decimal("15.00"),
                status=BillStatus.OVERDUE,
                water_usage_gallons=5800
            ),
        ]

        for bill in bills:
            session.add(bill)

        await session.commit()

        print("Test data added successfully!")
        print(f"  - {len(props)} properties")
        print(f"  - {len(bills)} bills")


if __name__ == "__main__":
    asyncio.run(main())
