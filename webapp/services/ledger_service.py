"""Shared tenant charge ledger used by managers and the tenant portal."""

from __future__ import annotations

import asyncio
import calendar
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    PaymentStatus,
    RentPayment,
    StripePayment,
    StripePaymentType,
    Tenant,
    TenantCharge,
    TenantLedgerEntry,
)


logger = logging.getLogger(__name__)


MONEY = Decimal("0.01")
BALANCE_REDUCING_TYPES = {"payment", "credit"}


def money(value) -> Decimal:
    """Return a two-decimal Decimal without passing through float arithmetic."""
    return Decimal(str(value or 0)).quantize(MONEY, rounding=ROUND_HALF_UP)


def _activity_totals(entries) -> tuple[Decimal, Decimal, Decimal]:
    """Calculate charge activity without touching unrelated ORM relationships."""
    applied = Decimal("0.00")
    pending = Decimal("0.00")
    refunded = Decimal("0.00")

    for entry in entries:
        amount = money(entry.amount)
        if entry.status == "pending" and entry.entry_type == "payment":
            pending += amount
        elif entry.status == "posted" and entry.entry_type in BALANCE_REDUCING_TYPES:
            applied += amount
        elif entry.status == "posted" and entry.entry_type == "reversal":
            applied -= amount
        elif entry.status == "posted" and entry.entry_type == "refund":
            refunded += amount

    return max(applied, Decimal("0.00")), pending, refunded


def charge_snapshot(charge: TenantCharge, *, as_of: date | None = None) -> dict:
    """Return display and balance information for one loaded charge."""
    today = as_of or date.today()
    applied, pending, refunded = _activity_totals(charge.ledger_entries)
    amount = money(charge.amount)
    outstanding = max(amount - applied, Decimal("0.00"))
    progress_percent = min(float(applied / amount * 100), 100.0) if amount > 0 else 0.0
    is_future_rent = charge.charge_type == "rent" and charge.due_date > today

    if charge.is_void:
        status = "void"
    elif outstanding <= 0:
        status = "paid"
    elif is_future_rent:
        status = "upcoming"
    elif charge.due_date < today:
        status = "overdue"
    elif applied > 0:
        status = "partial"
    else:
        status = "open"

    return {
        "record": charge,
        "id": charge.id,
        "tenant_id": charge.tenant_id,
        "property_id": charge.property_id,
        "tenant_name": charge.tenant_ref.name if charge.tenant_ref else "—",
        "property_address": charge.property_ref.address if charge.property_ref else "—",
        "charge_type": charge.charge_type,
        "description": charge.description,
        "amount": amount,
        "applied": applied,
        "pending": pending,
        "refunded": refunded,
        "outstanding": Decimal("0.00") if charge.is_void else outstanding,
        "progress_percent": progress_percent,
        "due_date": charge.due_date,
        "service_start": charge.service_start,
        "service_end": charge.service_end,
        "status": status,
        "is_future_rent": is_future_rent,
        "is_partial": applied > 0 and outstanding > 0,
        "is_recurring": charge.is_recurring,
        "recurrence_group": getattr(charge, "recurrence_group", None),
        "can_void": can_void_charge(charge),
        "void_reason": getattr(charge, "void_reason", None),
        "created_at": getattr(charge, "created_at", None),
        "entries": sorted(charge.ledger_entries, key=lambda item: item.created_at or datetime.min, reverse=True),
    }


def can_void_charge(charge: TenantCharge) -> bool:
    """A charge can be voided only before money or pending payment is attached."""
    applied, pending, _ = _activity_totals(charge.ledger_entries)
    return (
        not charge.is_void
        and applied <= 0
        and pending <= 0
    )


def stop_automatic_late_fees(tenant) -> bool:
    """Disable future automatic late fees for one tenant schedule."""
    changed = bool(
        getattr(tenant, "late_fee_initial_enabled", False)
        or getattr(tenant, "late_fee_daily_enabled", False)
    )
    tenant.late_fee_initial_enabled = False
    tenant.late_fee_daily_enabled = False
    return changed


def validate_payment_allocations(
    charges: Iterable[TenantCharge],
    *,
    tenant_id: int,
    charge_ids: Iterable[int],
    amounts: dict[int, object],
) -> list[tuple[TenantCharge, Decimal]]:
    """Validate a manual payment split against live charge balances."""
    ordered_ids = list(dict.fromkeys(charge_ids))
    charge_by_id = {charge.id: charge for charge in charges}
    if not ordered_ids or len(charge_by_id) != len(ordered_ids):
        raise ValueError("Unknown charge")

    allocations = []
    for charge_id in ordered_ids:
        charge = charge_by_id.get(charge_id)
        if not charge or charge.tenant_id != tenant_id or charge.is_void:
            raise ValueError("Charge does not belong to tenant")
        try:
            amount = money(Decimal(str(amounts.get(charge_id, "0"))))
        except Exception as exc:
            raise ValueError("Invalid allocation") from exc
        outstanding = charge_snapshot(charge)["outstanding"]
        if amount <= 0 or amount > outstanding:
            raise ValueError("Invalid allocation")
        allocations.append((charge, amount))
    return allocations


def _ordinal_day(day: int) -> str:
    if 10 <= day % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def tenant_rent_amount(tenant) -> Decimal:
    """Return the tenant-facing portion used for recurring rent charges."""
    value = getattr(tenant, "current_rent", None)
    if getattr(tenant, "is_section8", False) and getattr(tenant, "tenant_portion", None) is not None:
        value = tenant.tenant_portion
    return money(value)


def group_charges_by_month(charges: Iterable[dict]) -> list[dict]:
    """Return newest-first charge groups keyed by the first day of each month."""
    ordered = sorted(
        charges,
        key=lambda charge: (charge["due_date"], charge.get("id", 0)),
        reverse=True,
    )
    groups: list[dict] = []
    for charge in ordered:
        month = charge["due_date"].replace(day=1)
        if not groups or groups[-1]["month"] != month:
            groups.append({"month": month, "charges": []})
        groups[-1]["charges"].append(charge)
    return groups


def scheduled_rent_due_date(tenant, month: date) -> date:
    """Return a valid configured rent due date inside ``month``."""
    due_day = max(1, min(int(getattr(tenant, "rent_due_day", 1) or 1), 31))
    last_day = calendar.monthrange(month.year, month.month)[1]
    return month.replace(day=min(due_day, last_day))


def monthly_charge_summaries(
    charges: Iterable[dict],
    tenant,
    *,
    as_of: date | None = None,
) -> list[dict]:
    """Collapse recurring charge instances into tenant-facing monthly schedules."""
    rows = list(charges)
    groups: dict[str, list[dict]] = {}
    rent_schedule_active = getattr(tenant, "rent_schedule_active", True) is not False
    for charge in rows:
        if not charge.get("is_recurring") or charge["status"] == "void":
            continue
        if charge.get("charge_type") == "rent" and not rent_schedule_active:
            continue
        group_key = (
            f"rent:{getattr(tenant, 'id', 'tenant')}"
            if charge.get("charge_type") == "rent"
            else charge.get("recurrence_group") or f"{charge['charge_type']}:{charge['amount']}:{charge['due_date'].day}"
        )
        groups.setdefault(group_key, []).append(charge)

    summaries = []
    today = as_of or date.today()
    for group_key, group_rows in groups.items():
        ordered = sorted(group_rows, key=lambda charge: (charge["due_date"], charge["id"]))
        future_rows = [charge for charge in ordered if charge["due_date"] > today]
        representative = future_rows[0] if future_rows else ordered[-1]
        charge_type = representative["charge_type"]
        start_date = min((charge.get("service_start") or charge["due_date"] for charge in ordered))
        end_date = max((charge.get("service_end") or charge["due_date"] for charge in ordered))
        if charge_type == "rent":
            configured_amount = tenant_rent_amount(tenant)
            if configured_amount > 0:
                representative = {**representative, "amount": configured_amount}
            configured_due_day = int(getattr(tenant, "rent_due_day", representative["due_date"].day) or 1)
            start_date = (
                getattr(tenant, "rent_schedule_start_date", None)
                or getattr(tenant, "lease_start_date", None)
                or start_date
            )
            end_date = (
                getattr(tenant, "rent_schedule_end_date", None)
                or getattr(tenant, "lease_end_date", None)
                or (end_date if len(ordered) > 1 else None)
            )
        elif len(ordered) == 1 and not representative.get("service_end"):
            end_date = None

        description = representative["description"].split(" — ", 1)[0]
        summaries.append({
            "key": group_key,
            "charge_type": charge_type,
            "description": "Rent" if charge_type == "rent" else description,
            "amount": representative["amount"],
            "due_day": configured_due_day if charge_type == "rent" else representative["due_date"].day,
            "due_label": _ordinal_day(configured_due_day if charge_type == "rent" else representative["due_date"].day),
            "start_date": start_date,
            "end_date": end_date,
            "next_due_date": future_rows[0]["due_date"] if future_rows else None,
            "open_balance": sum(
                (charge["outstanding"] for charge in ordered if charge["status"] in {"open", "partial", "overdue"}),
                Decimal("0.00"),
            ),
            "charge_count": len(ordered),
            "representative": representative,
            "source": "Blue Deer rent schedule" if charge_type == "rent" else "Recurring charge series",
        })

    if rent_schedule_active and not any(summary["charge_type"] == "rent" for summary in summaries):
        rent_rows = [
            charge for charge in rows
            if charge["charge_type"] == "rent" and charge["status"] != "void"
        ]
        representative = max(rent_rows, key=lambda charge: charge["due_date"]) if rent_rows else None
        rent_source = tenant_rent_amount(tenant)
        if rent_source <= 0 and representative:
            rent_source = representative["amount"]
        rent_amount = money(rent_source)
        if rent_amount > 0:
            due_day = int(getattr(tenant, "rent_due_day", None) or (representative["due_date"].day if representative else 1))
            summaries.append({
                "key": f"lease-rent:{getattr(tenant, 'id', 'tenant')}",
                "charge_type": "rent",
                "description": "Rent",
                "amount": rent_amount,
                "due_day": due_day,
                "due_label": _ordinal_day(due_day),
                "start_date": getattr(tenant, "rent_schedule_start_date", None) or getattr(tenant, "lease_start_date", None),
                "end_date": getattr(tenant, "rent_schedule_end_date", None) or getattr(tenant, "lease_end_date", None),
                "next_due_date": None,
                "open_balance": sum(
                    (charge["outstanding"] for charge in rent_rows if charge["status"] in {"open", "partial", "overdue"}),
                    Decimal("0.00"),
                ),
                "charge_count": len(rent_rows),
                "representative": representative,
                "source": "Blue Deer rent schedule",
            })

    return sorted(
        summaries,
        key=lambda summary: (0 if summary["charge_type"] == "rent" else 1, summary["description"].lower()),
    )


async def list_charges(
    *,
    tenant_id: int | None = None,
    property_id: int | None = None,
    include_paid: bool = True,
) -> list[dict]:
    """Load charge snapshots, optionally scoped to one property or tenant."""
    async with get_session() as session:
        query = (
            select(TenantCharge)
            .options(
                selectinload(TenantCharge.tenant_ref),
                selectinload(TenantCharge.property_ref),
                selectinload(TenantCharge.ledger_entries),
            )
            .order_by(TenantCharge.due_date.desc(), TenantCharge.id.desc())
        )
        if tenant_id:
            query = query.where(TenantCharge.tenant_id == tenant_id)
        if property_id:
            query = query.where(TenantCharge.property_id == property_id)
        result = await session.execute(query)
        snapshots = [charge_snapshot(charge) for charge in result.scalars().all()]

    if include_paid:
        return snapshots
    return [item for item in snapshots if item["status"] in {"open", "partial", "overdue"}]


async def get_charge(charge_id: int, *, tenant_id: int | None = None) -> dict | None:
    """Load one charge snapshot with optional tenant ownership enforcement."""
    async with get_session() as session:
        query = (
            select(TenantCharge)
            .where(TenantCharge.id == charge_id)
            .options(
                selectinload(TenantCharge.tenant_ref),
                selectinload(TenantCharge.property_ref),
                selectinload(TenantCharge.ledger_entries),
            )
        )
        if tenant_id:
            query = query.where(TenantCharge.tenant_id == tenant_id)
        result = await session.execute(query)
        charge = result.scalar_one_or_none()
        return charge_snapshot(charge) if charge else None


async def ensure_monthly_rent_charge(tenant_id: int, for_month: date | None = None) -> int | None:
    """Create the tenant's current recurring rent charge once, unless legacy data says it is paid."""
    month = (for_month or date.today()).replace(day=1)
    if month.month == 12:
        next_month = month.replace(year=month.year + 1, month=1)
    else:
        next_month = month.replace(month=month.month + 1)
    unique_key = f"rent:{tenant_id}:{month.isoformat()}"

    try:
        async with get_session() as session:
            # A manager-created rent charge for this month also satisfies the schedule.
            existing_result = await session.execute(
                select(TenantCharge).where(
                    TenantCharge.tenant_id == tenant_id,
                    TenantCharge.is_void == False,
                    or_(
                        TenantCharge.unique_key == unique_key,
                        and_(
                            TenantCharge.charge_type == "rent",
                            TenantCharge.due_date >= month,
                            TenantCharge.due_date < next_month,
                        ),
                    ),
                ).limit(1)
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                return existing.id

            tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = tenant_result.scalar_one_or_none()
            if not tenant or not tenant.is_active or getattr(tenant, "rent_schedule_active", True) is False:
                return None

            due_date = scheduled_rent_due_date(tenant, month)
            schedule_start = getattr(tenant, "rent_schedule_start_date", None) or tenant.lease_start_date
            schedule_end = getattr(tenant, "rent_schedule_end_date", None) or tenant.lease_end_date
            if schedule_start and due_date < schedule_start:
                return None
            if schedule_end and due_date > schedule_end:
                return None

            # Do not generate a new receivable over a successful pre-ledger payment.
            legacy_ach = await session.execute(
                select(RentPayment.id).where(
                    RentPayment.tenant_id == tenant_id,
                    RentPayment.payment_month == month,
                    RentPayment.status.in_([
                        PaymentStatus.PENDING,
                        PaymentStatus.PROCESSING,
                        PaymentStatus.COMPLETED,
                    ]),
                ).limit(1)
            )
            legacy_card = await session.execute(
                select(StripePayment.id).where(
                    StripePayment.tenant_id == tenant_id,
                    StripePayment.payment_type == StripePaymentType.RENT,
                    StripePayment.payment_month == month,
                    StripePayment.status.in_([
                        PaymentStatus.PENDING,
                        PaymentStatus.PROCESSING,
                        PaymentStatus.COMPLETED,
                    ]),
                ).limit(1)
            )
            if legacy_ach.scalar_one_or_none() or legacy_card.scalar_one_or_none():
                return None

            amount = tenant_rent_amount(tenant)
            if amount <= 0:
                return None

            charge = TenantCharge(
                tenant_id=tenant.id,
                property_id=tenant.property_id,
                charge_type="rent",
                description=f"Rent — {month.strftime('%B %Y')}",
                amount=amount,
                due_date=due_date,
                service_start=month,
                is_recurring=True,
                recurrence_group=f"rent:{tenant.id}",
                unique_key=unique_key,
            )
            session.add(charge)
            await session.flush()
            return charge.id
    except IntegrityError:
        # Multiple app replicas may create the same unique monthly charge together.
        async with get_session() as session:
            existing_result = await session.execute(
                select(TenantCharge.id).where(TenantCharge.unique_key == unique_key)
            )
            return existing_result.scalar_one_or_none()


async def ensure_all_monthly_rent_charges(for_month: date | None = None) -> int:
    """Ensure every active tenant has the current rent receivable exactly once."""
    month = (for_month or date.today()).replace(day=1)
    if month.month == 12:
        next_month = month.replace(year=month.year + 1, month=1)
    else:
        next_month = month.replace(month=month.month + 1)
    async with get_session() as session:
        result = await session.execute(select(Tenant.id).where(Tenant.is_active == True))
        tenant_ids = list(result.scalars().all())
        existing_result = await session.execute(
            select(TenantCharge.tenant_id).where(
                TenantCharge.charge_type == "rent",
                TenantCharge.is_void == False,
                TenantCharge.due_date >= month,
                TenantCharge.due_date < next_month,
            )
        )
        existing_tenant_ids = set(existing_result.scalars().all())

    created = 0
    for tenant_id in tenant_ids:
        if tenant_id in existing_tenant_ids:
            continue
        try:
            charge_id = await ensure_monthly_rent_charge(tenant_id, month)
            if charge_id:
                created += 1
        except Exception as exc:
            # Another app replica may have inserted the unique monthly charge first.
            logger.warning("Could not ensure rent charge for tenant %s: %s", tenant_id, exc)
    return created


async def monthly_charge_loop():
    """Keep monthly rent receivables current while the app remains online."""
    while True:
        try:
            await ensure_all_monthly_rent_charges()
        except Exception as exc:
            logger.warning("Monthly charge generation skipped: %s", exc)
        await asyncio.sleep(60 * 60 * 6)


async def post_external_payment(
    *,
    provider: str,
    external_id: str,
    charge_id: int | None,
    tenant_id: int,
    property_id: int,
    amount,
    payment_method: str,
    description: str,
) -> int | None:
    """Post an idempotent provider payment to the ledger after settlement."""
    if not charge_id or not external_id or money(amount) <= 0:
        return None

    async with get_session() as session:
        existing = await session.execute(
            select(TenantLedgerEntry.id).where(
                TenantLedgerEntry.external_provider == provider,
                TenantLedgerEntry.external_id == external_id,
                TenantLedgerEntry.entry_type == "payment",
            )
        )
        existing_id = existing.scalar_one_or_none()
        if existing_id:
            return existing_id

        charge_result = await session.execute(
            select(TenantCharge).where(
                TenantCharge.id == charge_id,
                TenantCharge.tenant_id == tenant_id,
                TenantCharge.property_id == property_id,
            )
        )
        charge = charge_result.scalar_one_or_none()
        if not charge:
            return None

        entry = TenantLedgerEntry(
            tenant_id=tenant_id,
            property_id=property_id,
            charge_id=charge_id,
            entry_type="payment",
            amount=money(amount),
            status="posted",
            payment_method=payment_method,
            description=description,
            external_provider=provider,
            external_id=external_id,
            occurred_on=date.today(),
        )
        session.add(entry)
        try:
            await session.flush()
            return entry.id
        except IntegrityError:
            await session.rollback()
            concurrent = await session.execute(
                select(TenantLedgerEntry.id).where(
                    TenantLedgerEntry.external_provider == provider,
                    TenantLedgerEntry.external_id == external_id,
                    TenantLedgerEntry.entry_type == "payment",
                )
            )
            return concurrent.scalar_one_or_none()


async def reverse_external_payment(
    *,
    provider: str,
    external_id: str,
    charge_id: int | None,
    tenant_id: int,
    property_id: int,
    amount,
    description: str,
) -> int | None:
    """Restore a charge balance once when a settled transfer is returned."""
    if not charge_id or not external_id or money(amount) <= 0:
        return None

    async with get_session() as session:
        original = await session.execute(
            select(TenantLedgerEntry.id).where(
                TenantLedgerEntry.external_provider == provider,
                TenantLedgerEntry.external_id == external_id,
                TenantLedgerEntry.entry_type == "payment",
                TenantLedgerEntry.status == "posted",
            )
        )
        if not original.scalar_one_or_none():
            return None

        existing = await session.execute(
            select(TenantLedgerEntry.id).where(
                TenantLedgerEntry.external_provider == provider,
                TenantLedgerEntry.external_id == external_id,
                TenantLedgerEntry.entry_type == "reversal",
            )
        )
        existing_id = existing.scalar_one_or_none()
        if existing_id:
            return existing_id

        entry = TenantLedgerEntry(
            tenant_id=tenant_id,
            property_id=property_id,
            charge_id=charge_id,
            entry_type="reversal",
            amount=money(amount),
            status="posted",
            payment_method="ach",
            description=description,
            external_provider=provider,
            external_id=external_id,
            occurred_on=date.today(),
        )
        session.add(entry)
        try:
            await session.flush()
            return entry.id
        except IntegrityError:
            await session.rollback()
            concurrent = await session.execute(
                select(TenantLedgerEntry.id).where(
                    TenantLedgerEntry.external_provider == provider,
                    TenantLedgerEntry.external_id == external_id,
                    TenantLedgerEntry.entry_type == "reversal",
                )
            )
            return concurrent.scalar_one_or_none()


def totals(charges: Iterable[dict]) -> dict:
    """Aggregate amounts that are due as of today for summary cards."""
    rows = list(charges)
    due_rows = [
        row for row in rows
        if row["status"] != "void" and not row.get("is_future_rent", False)
    ]
    return {
        "charged": sum((row["amount"] for row in due_rows), Decimal("0.00")),
        "paid_or_credited": sum((row["applied"] for row in due_rows), Decimal("0.00")),
        "outstanding": sum((row["outstanding"] for row in due_rows), Decimal("0.00")),
        "overdue": sum((row["outstanding"] for row in due_rows if row["status"] == "overdue"), Decimal("0.00")),
    }
