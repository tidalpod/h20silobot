"""Shared tenant charge ledger used by managers and the tenant portal."""

import asyncio
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


def charge_snapshot(charge: TenantCharge) -> dict:
    """Return display and balance information for one loaded charge."""
    applied = Decimal("0.00")
    pending = Decimal("0.00")
    refunded = Decimal("0.00")

    for entry in charge.ledger_entries:
        amount = money(entry.amount)
        if entry.status == "pending" and entry.entry_type == "payment":
            pending += amount
        elif entry.status == "posted" and entry.entry_type in BALANCE_REDUCING_TYPES:
            applied += amount
        elif entry.status == "posted" and entry.entry_type == "reversal":
            applied -= amount
        elif entry.status == "posted" and entry.entry_type == "refund":
            refunded += amount

    applied = max(applied, Decimal("0.00"))
    amount = money(charge.amount)
    outstanding = max(amount - applied, Decimal("0.00"))
    progress_percent = min(float(applied / amount * 100), 100.0) if amount > 0 else 0.0

    if charge.is_void:
        status = "void"
    elif outstanding <= 0:
        status = "paid"
    elif charge.due_date < date.today():
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
        "is_partial": applied > 0 and outstanding > 0,
        "is_recurring": charge.is_recurring,
        "entries": sorted(charge.ledger_entries, key=lambda item: item.created_at or datetime.min, reverse=True),
    }


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
    return [item for item in snapshots if item["status"] not in {"paid", "void"}]


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
            if not tenant or not tenant.is_active:
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

            rent_source = tenant.current_rent
            if tenant.is_section8 and tenant.tenant_portion is not None:
                rent_source = tenant.tenant_portion
            amount = money(rent_source)
            if amount <= 0:
                return None

            charge = TenantCharge(
                tenant_id=tenant.id,
                property_id=tenant.property_id,
                charge_type="rent",
                description=f"Rent — {month.strftime('%B %Y')}",
                amount=amount,
                due_date=month,
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
    """Aggregate snapshots for summary cards."""
    rows = list(charges)
    return {
        "charged": sum((row["amount"] for row in rows if row["status"] != "void"), Decimal("0.00")),
        "paid_or_credited": sum((row["applied"] for row in rows if row["status"] != "void"), Decimal("0.00")),
        "outstanding": sum((row["outstanding"] for row in rows), Decimal("0.00")),
        "overdue": sum((row["outstanding"] for row in rows if row["status"] == "overdue"), Decimal("0.00")),
    }
