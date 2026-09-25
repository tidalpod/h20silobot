#!/usr/bin/env python3
"""Reconcile and optionally import TurboTenant payment history."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models import (
    ExternalPayment,
    Property,
    Tenant,
    TenantCharge,
    TenantLedgerEntry,
)
from webapp.services.turbotenant_import import (
    PropertyRecord,
    TenantRecord,
    build_report,
    map_charge_type,
    map_payment_method,
    match_charges,
    match_deposits,
    read_charges,
    read_deposits,
    read_rent_roll,
)


def get_database_url() -> str:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required. Use `railway run` for the production import.")
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


async def load_database_snapshot(engine) -> tuple[list[PropertyRecord], list[TenantRecord], set[str], set[str]]:
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
                    select(ExternalPayment.external_id).where(
                        ExternalPayment.external_provider == "turbotenant"
                    )
                )
            ).scalars().all()
        )

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


async def apply_matches(
    *,
    engine,
    charges,
    deposits,
    properties,
    tenants,
    excluded_property_addresses,
    excluded_lease_titles,
) -> dict:
    """Insert only deterministic matches in one atomic, idempotent transaction."""
    excluded_properties = [
        PropertyRecord(-(index + 1), address)
        for index, address in enumerate(excluded_property_addresses)
    ]
    deposit_matches = match_deposits(deposits, properties, tenants, excluded_properties)
    charge_matches = match_charges(
        charges,
        deposits,
        deposit_matches,
        properties,
        tenants,
        excluded_properties,
        excluded_lease_titles,
    )

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    stats = {
        "payments_inserted": 0,
        "payments_skipped_existing": 0,
        "payments_amount": "0.00",
        "charges_inserted": 0,
        "charges_skipped_existing": 0,
        "charges_amount": "0.00",
        "charge_payments_inserted": 0,
        "charge_payments_amount": "0.00",
    }
    payment_amount = 0
    charge_amount = 0
    charge_payment_amount = 0

    async with session_factory() as session:
        async with session.begin():
            existing_payment_ids = set(
                (
                    await session.execute(
                        select(ExternalPayment.external_id).where(
                            ExternalPayment.external_provider == "turbotenant"
                        )
                    )
                ).scalars().all()
            )
            existing_charge_keys = set(
                (
                    await session.execute(
                        select(TenantCharge.unique_key).where(
                            TenantCharge.unique_key.like("turbotenant:charge:%")
                        )
                    )
                ).scalars().all()
            )

            for row, match in zip(deposits, deposit_matches):
                if match.status != "matched":
                    continue
                if row.payment_id in existing_payment_ids:
                    stats["payments_skipped_existing"] += 1
                    continue
                if not match.property_id or not match.tenant_id:
                    raise RuntimeError(f"Matched deposit row {row.row_number} has no database target")
                session.add(ExternalPayment(
                    tenant_id=match.tenant_id,
                    property_id=match.property_id,
                    external_provider="turbotenant",
                    external_id=row.payment_id,
                    amount=row.amount,
                    payment_method=map_payment_method(row.payment_method),
                    status="completed",
                    description=(row.note or f"TurboTenant payment - {row.lease_title}")[:255],
                    note=row.note or None,
                    paid_on=row.paid_on,
                    deposited_on=row.deposited_on,
                    source_lease=row.lease_title[:255] or None,
                    source_bank=row.bank_account[:255] or None,
                ))
                existing_payment_ids.add(row.payment_id)
                stats["payments_inserted"] += 1
                payment_amount += row.amount

            for row, match in zip(charges, charge_matches):
                if match.status != "matched":
                    continue
                if row.source_key in existing_charge_keys:
                    stats["charges_skipped_existing"] += 1
                    continue
                if not match.property_id or not match.tenant_id:
                    raise RuntimeError(f"Matched charge row {row.row_number} has no database target")

                charge_type = map_charge_type(row.category)
                description = row.description or row.category.replace("_", " ").title()
                charge = TenantCharge(
                    tenant_id=match.tenant_id,
                    property_id=match.property_id,
                    charge_type=charge_type,
                    description=description[:255],
                    amount=row.amount,
                    due_date=row.due_date,
                    service_start=row.due_date.replace(day=1) if charge_type == "rent" else None,
                    is_recurring=False,
                    unique_key=row.source_key,
                )
                session.add(charge)
                await session.flush()
                existing_charge_keys.add(row.source_key)
                stats["charges_inserted"] += 1
                charge_amount += row.amount

                if row.paid_amount > 0:
                    session.add(TenantLedgerEntry(
                        tenant_id=match.tenant_id,
                        property_id=match.property_id,
                        charge_id=charge.id,
                        entry_type="payment",
                        amount=row.paid_amount,
                        status="posted",
                        payment_method="imported",
                        description="TurboTenant historical payment",
                        note=f"Imported charge status: {row.status}",
                        external_provider="turbotenant_charge",
                        external_id=row.source_key,
                        occurred_on=row.due_date,
                    ))
                    stats["charge_payments_inserted"] += 1
                    charge_payment_amount += row.paid_amount

    stats["payments_amount"] = f"{payment_amount:.2f}"
    stats["charges_amount"] = f"{charge_amount:.2f}"
    stats["charge_payments_amount"] = f"{charge_payment_amount:.2f}"
    return stats


async def run(args: argparse.Namespace) -> tuple[dict, dict | None]:
    source_dir = args.source_dir.resolve()
    charges = read_charges(source_dir / "charges_all_time.csv")
    deposits = read_deposits(source_dir / "deposits_all_time.csv")
    rent_roll = read_rent_roll(source_dir / "rent_roll.csv")
    engine = create_async_engine(get_database_url())
    try:
        properties, tenants, charge_keys, payment_ids = await load_database_snapshot(engine)
        report = build_report(
            charges=charges,
            deposits=deposits,
            rent_roll=rent_roll,
            properties=properties,
            tenants=tenants,
            existing_charge_keys=charge_keys,
            existing_payment_ids=payment_ids,
            excluded_property_addresses=args.exclude_property,
            excluded_lease_titles=args.exclude_lease,
        )
        applied = None
        if args.apply:
            applied = await apply_matches(
                engine=engine,
                charges=charges,
                deposits=deposits,
                properties=properties,
                tenants=tenants,
                excluded_property_addresses=args.exclude_property,
                excluded_lease_titles=args.exclude_lease,
            )
            report["mode"] = "apply"
            report["applied"] = applied
        return report, applied
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile TurboTenant exports and optionally import deterministic matches."
    )
    parser.add_argument("source_dir", type=Path, help="Directory containing the three exported CSV files")
    parser.add_argument("--report", type=Path, help="JSON report path (defaults inside source_dir)")
    parser.add_argument(
        "--exclude-property",
        action="append",
        default=[],
        help="TurboTenant property address to classify as out of scope; may be repeated",
    )
    parser.add_argument(
        "--exclude-lease",
        action="append",
        default=[],
        help="Exact TurboTenant lease title to classify as out of scope; may be repeated",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Import matched rows. Without this flag the command is read-only.",
    )
    args = parser.parse_args()

    try:
        report, applied = asyncio.run(run(args))
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
    print(f"{'Import' if args.apply else 'Dry run'} complete: {report_path}")
    print(
        "Deposits: "
        f"{deposit_summary['matched']}/{deposit_summary['importable']} importable matched "
        f"(${deposit_summary['matched_amount']} of ${deposit_summary['importable_amount']}); "
        f"{deposit_summary['excluded']} excluded"
    )
    print(
        "Charges: "
        f"{charge_summary['matched']}/{charge_summary['importable']} importable matched "
        f"(${charge_summary['matched_amount']} of ${charge_summary['importable_amount']}); "
        f"{charge_summary['excluded']} excluded"
    )
    print(
        "Needs review: "
        f"{deposit_summary['ambiguous'] + deposit_summary['unmatched']} deposits, "
        f"{charge_summary['ambiguous'] + charge_summary['unmatched']} charges"
    )
    if applied:
        print(
            "Imported: "
            f"{applied['payments_inserted']} payments (${applied['payments_amount']}), "
            f"{applied['charges_inserted']} charges (${applied['charges_amount']}), "
            f"{applied['charge_payments_inserted']} charge allocations "
            f"(${applied['charge_payments_amount']})"
        )
        print(
            "Already present: "
            f"{applied['payments_skipped_existing']} payments, "
            f"{applied['charges_skipped_existing']} charges"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
