#!/usr/bin/env python3
"""Create a read-only TurboTenant import reconciliation report."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models import Property, Tenant, TenantCharge, TenantLedgerEntry
from webapp.services.turbotenant_import import (
    PropertyRecord,
    TenantRecord,
    build_report,
    read_charges,
    read_deposits,
    read_rent_roll,
)


async def load_database_snapshot() -> tuple[list[PropertyRecord], list[TenantRecord], set[str], set[str]]:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required. Use `railway run` for the production dry run.")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            property_rows = (
                await connection.execute(
                    select(Property.id, Property.address, Property.city, Property.state, Property.zip_code)
                )
            ).all()
            tenant_rows = (
                await connection.execute(
                    select(Tenant.id, Tenant.property_id, Tenant.name, Tenant.is_active)
                )
            ).all()
            existing_charge_keys = set(
                (
                    await connection.execute(
                        select(TenantCharge.unique_key).where(
                            TenantCharge.unique_key.like("turbotenant:charge:%")
                        )
                    )
                ).scalars().all()
            )
            existing_payment_ids = set(
                (
                    await connection.execute(
                        select(TenantLedgerEntry.external_id).where(
                            TenantLedgerEntry.external_provider == "turbotenant"
                        )
                    )
                ).scalars().all()
            )
    finally:
        await engine.dispose()

    properties = [
        PropertyRecord(
            id=row.id,
            address=row.address or "",
            city=row.city or "",
            state=row.state or "",
            zip_code=row.zip_code or "",
        )
        for row in property_rows
    ]
    tenants = [
        TenantRecord(
            id=row.id,
            property_id=row.property_id,
            name=row.name or "",
            is_active=bool(row.is_active),
        )
        for row in tenant_rows
    ]
    return properties, tenants, existing_charge_keys, existing_payment_ids


async def run(args: argparse.Namespace) -> dict:
    source_dir = args.source_dir.resolve()
    charges = read_charges(source_dir / "charges_all_time.csv")
    deposits = read_deposits(source_dir / "deposits_all_time.csv")
    rent_roll = read_rent_roll(source_dir / "rent_roll.csv")
    properties, tenants, charge_keys, payment_ids = await load_database_snapshot()
    return build_report(
        charges=charges,
        deposits=deposits,
        rent_roll=rent_roll,
        properties=properties,
        tenants=tenants,
        existing_charge_keys=charge_keys,
        existing_payment_ids=payment_ids,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Match TurboTenant exports to Blue Deer without changing the database."
    )
    parser.add_argument("source_dir", type=Path, help="Directory containing the three exported CSV files")
    parser.add_argument("--report", type=Path, help="JSON report path (defaults inside source_dir)")
    args = parser.parse_args()

    try:
        report = asyncio.run(run(args))
    except Exception as exc:
        print(f"TurboTenant dry run failed: {exc}", file=sys.stderr)
        return 1

    report_path = (args.report or args.source_dir / "dry_run_report.json").resolve()
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    try:
        report_path.chmod(0o600)
    except OSError:
        pass

    deposit_summary = report["matches"]["deposits"]
    charge_summary = report["matches"]["charges"]
    print(f"Dry run complete: {report_path}")
    print(
        "Deposits: "
        f"{deposit_summary['matched']}/{deposit_summary['total']} matched "
        f"(${deposit_summary['matched_amount']} of ${deposit_summary['total_amount']})"
    )
    print(
        "Charges: "
        f"{charge_summary['matched']}/{charge_summary['total']} matched "
        f"(${charge_summary['matched_amount']} of ${charge_summary['total_amount']})"
    )
    print(
        "Needs review: "
        f"{deposit_summary['ambiguous'] + deposit_summary['unmatched']} deposits, "
        f"{charge_summary['ambiguous'] + charge_summary['unmatched']} charges"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

