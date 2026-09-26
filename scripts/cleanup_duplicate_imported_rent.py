#!/usr/bin/env python3
"""Remove empty generated rent charges superseded by paid TurboTenant history.

The command is a dry run unless ``--delete`` is supplied.  Destructive runs
also require ``--confirm-count`` and write a JSON recovery snapshot before the
transaction is committed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.models import Property, RentPayment, StripePayment, Tenant, TenantCharge


def database_url() -> str:
    load_dotenv()
    value = os.getenv("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL is required. Use `railway run` for production.")
    if value.startswith("postgresql://"):
        value = value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def parse_month(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("month must use YYYY-MM format") from exc


def next_month(value: date) -> date:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def posted_applied_amount(charge: TenantCharge) -> Decimal:
    total = Decimal("0.00")
    for entry in charge.ledger_entries:
        if entry.status != "posted":
            continue
        amount = Decimal(str(entry.amount or 0))
        if entry.entry_type in {"payment", "credit"}:
            total += amount
        elif entry.entry_type == "reversal":
            total -= amount
    return total


def serialize_charge(charge: TenantCharge) -> dict:
    return {
        "id": charge.id,
        "tenant_id": charge.tenant_id,
        "tenant": charge.tenant_ref.name,
        "property_id": charge.property_id,
        "property": charge.property_ref.address,
        "charge_type": charge.charge_type,
        "description": charge.description,
        "amount": str(charge.amount),
        "due_date": charge.due_date.isoformat(),
        "service_start": charge.service_start.isoformat() if charge.service_start else None,
        "service_end": charge.service_end.isoformat() if charge.service_end else None,
        "is_recurring": charge.is_recurring,
        "recurrence_group": charge.recurrence_group,
        "unique_key": charge.unique_key,
        "created_by_user_id": charge.created_by_user_id,
        "created_at": charge.created_at.isoformat() if charge.created_at else None,
        "updated_at": charge.updated_at.isoformat() if charge.updated_at else None,
    }


async def find_candidates(session, month: date) -> list[tuple[TenantCharge, TenantCharge]]:
    month_end = next_month(month)
    load_refs = (
        selectinload(TenantCharge.tenant_ref),
        selectinload(TenantCharge.property_ref),
        selectinload(TenantCharge.ledger_entries),
    )

    generated = list(
        (
            await session.execute(
                select(TenantCharge)
                .where(
                    TenantCharge.charge_type == "rent",
                    TenantCharge.is_void == False,
                    TenantCharge.is_recurring == True,
                    TenantCharge.due_date >= month,
                    TenantCharge.due_date < month_end,
                    TenantCharge.unique_key.like("rent:%"),
                )
                .options(*load_refs)
                .order_by(TenantCharge.tenant_id, TenantCharge.id)
            )
        )
        .scalars()
        .all()
    )
    imported = list(
        (
            await session.execute(
                select(TenantCharge)
                .where(
                    TenantCharge.charge_type == "rent",
                    TenantCharge.is_void == False,
                    TenantCharge.due_date >= month,
                    TenantCharge.due_date < month_end,
                    TenantCharge.unique_key.like("turbotenant:charge:%"),
                )
                .options(*load_refs)
                .order_by(TenantCharge.tenant_id, TenantCharge.id)
            )
        )
        .scalars()
        .all()
    )

    paid_imports: dict[int, list[TenantCharge]] = {}
    for charge in imported:
        if posted_applied_amount(charge) >= Decimal(str(charge.amount)):
            paid_imports.setdefault(charge.tenant_id, []).append(charge)

    generated_ids = [charge.id for charge in generated]
    linked_ids: set[int] = set()
    if generated_ids:
        linked_ids.update(
            value
            for value in (
                await session.execute(
                    select(RentPayment.charge_id).where(RentPayment.charge_id.in_(generated_ids))
                )
            ).scalars()
            if value is not None
        )
        linked_ids.update(
            value
            for value in (
                await session.execute(
                    select(StripePayment.charge_id).where(StripePayment.charge_id.in_(generated_ids))
                )
            ).scalars()
            if value is not None
        )

    candidates: list[tuple[TenantCharge, TenantCharge]] = []
    expected_month_key = month.isoformat()
    for charge in generated:
        if charge.unique_key != f"rent:{charge.tenant_id}:{expected_month_key}":
            continue
        if charge.ledger_entries or charge.id in linked_ids:
            continue
        matches = paid_imports.get(charge.tenant_id, [])
        if len(matches) == 1:
            candidates.append((charge, matches[0]))
    return candidates


async def print_imported_history(session, candidates, through_month: date) -> None:
    tenant_ids = sorted({generated.tenant_id for generated, _ in candidates})
    if not tenant_ids:
        return
    charges = list(
        (
            await session.execute(
                select(TenantCharge)
                .where(
                    TenantCharge.tenant_id.in_(tenant_ids),
                    TenantCharge.charge_type == "rent",
                    TenantCharge.unique_key.like("turbotenant:charge:%"),
                    TenantCharge.due_date < next_month(through_month),
                )
                .options(
                    selectinload(TenantCharge.tenant_ref),
                    selectinload(TenantCharge.ledger_entries),
                )
                .order_by(TenantCharge.tenant_id, TenantCharge.due_date.desc(), TenantCharge.id.desc())
            )
        )
        .scalars()
        .all()
    )
    print("\nImported rent history through the audited month:")
    print("tenant | due_date | description | amount | applied")
    for charge in charges:
        print(
            f"{charge.tenant_ref.name} | {charge.due_date.isoformat()} | {charge.description} | "
            f"${charge.amount} | ${posted_applied_amount(charge)}"
        )


async def run(args: argparse.Namespace) -> int:
    engine = create_async_engine(database_url())
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            candidates = await find_candidates(session, args.month)
            snapshot = {
                "created_at": datetime.utcnow().isoformat() + "Z",
                "month": args.month.strftime("%Y-%m"),
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "generated_charge": serialize_charge(generated),
                        "matching_imported_charge": {
                            **serialize_charge(imported),
                            "posted_applied": str(posted_applied_amount(imported)),
                        },
                    }
                    for generated, imported in candidates
                ],
            }

            print(
                "generated_id | tenant | section8 | current_rent | tenant_portion | property | "
                "generated_amount | imported_id | imported_description | imported_amount | applied"
            )
            for generated, imported in candidates:
                print(
                    f"{generated.id} | {generated.tenant_ref.name} | {generated.tenant_ref.is_section8} | "
                    f"${generated.tenant_ref.current_rent or 0} | ${generated.tenant_ref.tenant_portion or 0} | "
                    f"{generated.property_ref.address} | ${generated.amount} | {imported.id} | "
                    f"{imported.description} | ${imported.amount} | ${posted_applied_amount(imported)}"
                )
            if args.history:
                await print_imported_history(session, candidates, args.month)
            if not args.delete:
                print(f"DRY RUN: {len(candidates)} generated charge(s) qualify for deletion.")
                return 0

            if args.confirm_count is None or args.confirm_count != len(candidates):
                raise RuntimeError(
                    f"Refusing deletion: --confirm-count must equal current candidate count ({len(candidates)})."
                )
            if not candidates:
                print("No matching charges to delete.")
                return 0

            backup_path = args.backup or Path(
                f"duplicate-rent-cleanup-{args.month.strftime('%Y-%m')}-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
            )
            backup_path.write_text(json.dumps(snapshot, indent=2) + "\n")
            for generated, _ in candidates:
                await session.delete(generated)
            await session.commit()
            print(f"DELETED: {len(candidates)} charge(s). Recovery snapshot: {backup_path.resolve()}")
            return 0
    finally:
        await engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, type=parse_month, help="Month to inspect, in YYYY-MM format")
    parser.add_argument("--delete", action="store_true", help="Commit deletion; default is a dry run")
    parser.add_argument("--confirm-count", type=int, help="Required exact candidate count for --delete")
    parser.add_argument("--backup", type=Path, help="JSON recovery snapshot path")
    parser.add_argument("--history", action="store_true", help="Print imported rent history for candidates")
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
