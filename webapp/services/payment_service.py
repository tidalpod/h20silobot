"""Payment business logic — balance calculation, payment initiation, autopay, webhooks"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Tenant, TenantBankAccount, RentPayment, TenantAutopay,
    PaymentStatus, AutopayStatus, EntityConfig, EntityBankAccount,
    StripePayment, StripePaymentType, PaymentProviderState,
)
from webapp.services import ledger_service, plaid_service

logger = logging.getLogger(__name__)

# Late fee config
GRACE_PERIOD_DAYS = 5
LATE_FEE_PER_DAY = Decimal("15.00")
MAX_PENALTY_DAYS = 5  # $75 max


def calculate_late_fee(
    for_date: date = None,
    *,
    due_date: date | None = None,
    initial_enabled: bool = False,
    initial_amount: Decimal = Decimal("0.00"),
    daily_enabled: bool = True,
    daily_amount: Decimal = LATE_FEE_PER_DAY,
    grace_days: int = GRACE_PERIOD_DAYS,
    limit_type: str = "days",
    max_days: int = MAX_PENALTY_DAYS,
    max_amount: Decimal | None = None,
) -> Decimal:
    """Calculate a configured late fee without mutating the ledger."""
    if for_date is None:
        for_date = date.today()
    due_date = due_date or for_date.replace(day=1)
    first_fee_date = due_date + timedelta(days=max(0, int(grace_days)))
    if for_date < first_fee_date:
        return Decimal("0.00")
    penalty_days = (for_date - first_fee_date).days + 1
    fee = Decimal(str(initial_amount or 0)) if initial_enabled else Decimal("0.00")
    if daily_enabled:
        daily_days = penalty_days
        if limit_type == "days":
            daily_days = min(daily_days, max(0, int(max_days)))
        fee += Decimal(str(daily_amount or 0)) * daily_days
    if limit_type == "amount" and max_amount is not None:
        fee = min(fee, Decimal(str(max_amount)))
    return ledger_service.money(max(fee, Decimal("0.00")))


def calculate_tenant_late_fee(tenant, due_date: date, for_date: date | None = None) -> Decimal:
    """Calculate one tenant's policy with backwards-compatible defaults."""
    return calculate_late_fee(
        for_date,
        due_date=due_date,
        initial_enabled=bool(getattr(tenant, "late_fee_initial_enabled", False)),
        initial_amount=Decimal(str(getattr(tenant, "late_fee_initial_amount", 0) or 0)),
        daily_enabled=bool(getattr(tenant, "late_fee_daily_enabled", True)),
        daily_amount=Decimal(str(getattr(tenant, "late_fee_daily_amount", LATE_FEE_PER_DAY) or 0)),
        grace_days=int(getattr(tenant, "late_fee_grace_days", GRACE_PERIOD_DAYS) or 0),
        limit_type=str(getattr(tenant, "late_fee_limit_type", "days") or "days"),
        max_days=int(getattr(tenant, "late_fee_max_days", MAX_PENALTY_DAYS) or 0),
        max_amount=getattr(tenant, "late_fee_max_amount", None),
    )


async def calculate_balance_due(tenant_id: int) -> dict:
    """Calculate the tenant's ledger balance, preserving the existing rent API shape."""
    today = date.today()
    current_month = today.replace(day=1)
    await ledger_service.ensure_monthly_rent_charge(tenant_id, current_month)
    charges = await ledger_service.list_charges(tenant_id=tenant_id, include_paid=False)
    outstanding = sum((item["outstanding"] for item in charges), Decimal("0.00"))
    current_rent = next(
        (
            item for item in charges
            if item["charge_type"] == "rent"
            and item["due_date"].year == current_month.year
            and item["due_date"].month == current_month.month
        ),
        None,
    )
    late_fee = Decimal("0.00")
    if current_rent and current_rent["outstanding"] > 0:
        async with get_session() as session:
            tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = tenant_result.scalar_one_or_none()
        if tenant:
            late_fee = calculate_tenant_late_fee(tenant, current_rent["due_date"], today)

    return {
        "rent_amount": current_rent["outstanding"] if current_rent else Decimal("0.00"),
        "late_fee": late_fee,
        "total_due": outstanding + late_fee,
        "ledger_due": outstanding,
        "payment_month": current_month,
        "paid": outstanding <= 0,
        "charges": charges,
    }


async def initiate_payment(
    tenant_id: int,
    bank_account_id: int,
    amount: Decimal,
    payment_month: date,
    is_autopay: bool = False,
    charge_id: int | None = None,
) -> dict:
    """Create a payment record and initiate Plaid transfer."""
    charge = None
    if charge_id:
        charge = await ledger_service.get_charge(charge_id, tenant_id=tenant_id)
        if not charge or charge["status"] in {"paid", "void", "upcoming"}:
            return {"error": "Charge is no longer payable"}
        amount = ledger_service.money(amount)
        if amount <= 0 or amount > charge["outstanding"]:
            return {"error": "Payment amount exceeds the charge balance"}

    async with get_session() as session:
        # Get tenant and bank account
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
            .options(selectinload(Tenant.property_ref))
        )
        tenant = tenant_result.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        bank_result = await session.execute(
            select(TenantBankAccount)
            .where(TenantBankAccount.id == bank_account_id)
            .where(TenantBankAccount.tenant_id == tenant_id)
            .where(TenantBankAccount.is_active == True)
        )
        bank_account = bank_result.scalar_one_or_none()
        if not bank_account:
            return {"error": "Bank account not found or inactive"}

        if charge_id:
            pending_result = await session.execute(
                select(RentPayment.id).where(
                    RentPayment.charge_id == charge_id,
                    RentPayment.status.in_([PaymentStatus.PENDING, PaymentStatus.PROCESSING]),
                ).limit(1)
            )
            if pending_result.scalar_one_or_none():
                return {"error": "A bank payment is already processing for this charge"}

        # Apply this tenant's configured policy only to the current rent period.
        late_fee = Decimal("0.00")
        today = date.today()
        if (not charge_id) or (
            charge
            and charge["charge_type"] == "rent"
            and charge["due_date"].year == today.year
            and charge["due_date"].month == today.month
        ):
            due_date = charge["due_date"] if charge else ledger_service.scheduled_rent_due_date(tenant, today.replace(day=1))
            late_fee = calculate_tenant_late_fee(tenant, due_date, today)
        total_amount = amount + late_fee

        # Look up entity bank account for payment routing
        entity_bank_account_id = None
        if tenant.property_ref and tenant.property_ref.entity:
            entity_result = await session.execute(
                select(EntityConfig)
                .where(EntityConfig.entity_name == tenant.property_ref.entity)
            )
            entity_config = entity_result.scalar_one_or_none()
            if entity_config:
                acct_result = await session.execute(
                    select(EntityBankAccount)
                    .where(EntityBankAccount.entity_id == entity_config.id)
                    .where(EntityBankAccount.is_default == True)
                    .where(EntityBankAccount.is_active == True)
                )
                entity_acct = acct_result.scalar_one_or_none()
                if entity_acct:
                    entity_bank_account_id = entity_acct.id

        # Create payment record
        payment = RentPayment(
            tenant_id=tenant_id,
            property_id=tenant.property_id,
            bank_account_id=bank_account_id,
            entity_bank_account_id=entity_bank_account_id,
            charge_id=charge_id,
            amount=amount,
            late_fee=late_fee,
            total_amount=total_amount,
            payment_month=payment_month,
            status=PaymentStatus.PENDING,
            is_autopay=is_autopay,
        )
        session.add(payment)
        await session.flush()

        # Initiate Plaid transfer
        description = charge["description"] if charge else f"Rent {payment_month.strftime('%b %Y')}"
        transfer_result = await plaid_service.create_transfer(
            access_token=bank_account.plaid_access_token,
            account_id=bank_account.plaid_account_id,
            amount=str(total_amount),
            description=description,
            legal_name=tenant.name,
            idempotency_key=f"blue-deer-payment-{payment.id}",
            metadata={
                "payment_id": payment.id,
                "tenant_id": tenant_id,
                "charge_id": charge_id or "",
            },
            ach_class="ppd" if is_autopay else "web",
        )

        payment.plaid_authorization_id = transfer_result.get("authorization_id")

        if "error" in transfer_result:
            payment.status = PaymentStatus.FAILED
            payment.failed_at = datetime.utcnow()
            payment.failure_reason = transfer_result["error"]
            return {"error": transfer_result["error"], "payment_id": payment.id}

        payment.plaid_transfer_id = transfer_result["transfer_id"]
        payment.plaid_transfer_status = transfer_result["status"]
        payment.status = PaymentStatus.PROCESSING

        return {
            "payment_id": payment.id,
            "transfer_id": transfer_result["transfer_id"],
            "status": transfer_result["status"],
            "total_amount": str(total_amount),
        }


async def _apply_transfer_status(transfer_id: str, plaid_status: str, failure_reason=None) -> dict:
    """Apply one Plaid event and mirror settled/returned money in the charge ledger."""
    payment_data = None
    async with get_session() as session:
        result = await session.execute(
            select(RentPayment).where(RentPayment.plaid_transfer_id == transfer_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning(f"No payment found for transfer {transfer_id}")
            return {"status": "ignored", "reason": "Payment not found"}

        payment.plaid_transfer_status = plaid_status
        if plaid_status in ("settled", "funds_available"):
            payment.status = PaymentStatus.COMPLETED
            payment.completed_at = payment.completed_at or datetime.utcnow()
        elif plaid_status in ("pending", "posted"):
            payment.status = PaymentStatus.PROCESSING
        elif plaid_status == "failed":
            payment.status = PaymentStatus.FAILED
            payment.failed_at = datetime.utcnow()
            if isinstance(failure_reason, dict):
                payment.failure_reason = (
                    failure_reason.get("description")
                    or failure_reason.get("message")
                    or str(failure_reason)
                )
            else:
                payment.failure_reason = str(failure_reason or "Transfer failed")
        elif plaid_status == "returned":
            payment.status = PaymentStatus.RETURNED
            payment.failed_at = datetime.utcnow()
            if isinstance(failure_reason, dict):
                payment.failure_reason = (
                    failure_reason.get("description")
                    or failure_reason.get("message")
                    or str(failure_reason)
                )
            else:
                payment.failure_reason = str(failure_reason or "Transfer returned by bank")
        elif plaid_status == "cancelled":
            payment.status = PaymentStatus.CANCELLED

        payment_data = {
            "id": payment.id,
            "status": payment.status.value,
            "charge_id": payment.charge_id,
            "tenant_id": payment.tenant_id,
            "property_id": payment.property_id,
            "amount": payment.amount,
        }

    if plaid_status in ("settled", "funds_available"):
        await ledger_service.post_external_payment(
            provider="plaid",
            external_id=transfer_id,
            charge_id=payment_data["charge_id"],
            tenant_id=payment_data["tenant_id"],
            property_id=payment_data["property_id"],
            amount=payment_data["amount"],
            payment_method="ach",
            description="Plaid ACH payment",
        )
    elif plaid_status == "returned":
        await ledger_service.reverse_external_payment(
            provider="plaid",
            external_id=transfer_id,
            charge_id=payment_data["charge_id"],
            tenant_id=payment_data["tenant_id"],
            property_id=payment_data["property_id"],
            amount=payment_data["amount"],
            description="ACH payment returned",
        )

    logger.info(f"Payment {payment_data['id']} updated to {payment_data['status']} (plaid: {plaid_status})")
    return {"status": "processed", "payment_id": payment_data["id"], "new_status": payment_data["status"]}


async def process_webhook(data: dict) -> dict:
    """Handle Plaid transfer webhook events."""
    webhook_type = data.get("webhook_type", "")
    webhook_code = data.get("webhook_code", "")

    if webhook_type != "TRANSFER":
        return {"status": "ignored", "reason": f"Not a transfer webhook: {webhook_type}"}

    # Older/direct webhook payloads may identify one transfer. Keep supporting them.
    transfer_id = data.get("transfer_id")
    if transfer_id:
        transfer_data = await plaid_service.get_transfer(transfer_id)
        if "error" in transfer_data:
            return {"status": "error", "reason": transfer_data["error"]}
        return await _apply_transfer_status(
            transfer_id,
            transfer_data.get("status", ""),
            transfer_data.get("failure_reason"),
        )

    if webhook_code != "TRANSFER_EVENTS_UPDATE":
        return {"status": "ignored", "reason": f"Unsupported transfer webhook: {webhook_code}"}

    async with get_session() as session:
        state_result = await session.execute(
            select(PaymentProviderState).where(PaymentProviderState.provider == "plaid_transfer")
        )
        state = state_result.scalar_one_or_none()
        cursor = int(state.cursor) if state else 0

    processed = 0
    while True:
        page = await plaid_service.sync_transfer_events(cursor)
        if "error" in page:
            return {"status": "error", "reason": page["error"], "processed": processed}

        events = page.get("events", [])
        for event in events:
            event_transfer_id = event.get("transfer_id")
            event_type = event.get("event_type", "")
            if event_transfer_id and event_type:
                await _apply_transfer_status(
                    event_transfer_id,
                    event_type,
                    event.get("failure_reason"),
                )
                processed += 1
            cursor = max(cursor, int(event.get("event_id") or cursor))

        async with get_session() as session:
            state_result = await session.execute(
                select(PaymentProviderState).where(PaymentProviderState.provider == "plaid_transfer")
            )
            state = state_result.scalar_one_or_none()
            if state:
                state.cursor = str(cursor)
                state.updated_at = datetime.utcnow()
            else:
                session.add(PaymentProviderState(provider="plaid_transfer", cursor=str(cursor)))

        if not page.get("has_more") or not events:
            break

    return {"status": "processed", "events": processed, "cursor": cursor}


async def run_autopay():
    """Process all active autopay tenants. Called by scheduler."""
    today = date.today()
    current_month = today.replace(day=1)

    async with get_session() as session:
        result = await session.execute(
            select(TenantAutopay)
            .where(TenantAutopay.status == AutopayStatus.ACTIVE)
            .where(TenantAutopay.pay_day == today.day)
            .options(
                selectinload(TenantAutopay.tenant_ref),
                selectinload(TenantAutopay.bank_account_ref),
            )
        )
        autopay_configs = result.scalars().all()

    processed = 0
    for config in autopay_configs:
        tenant = config.tenant_ref
        if not tenant or not tenant.is_active:
            continue

        charge_id = await ledger_service.ensure_monthly_rent_charge(tenant.id, current_month)
        charge = await ledger_service.get_charge(charge_id, tenant_id=tenant.id) if charge_id else None
        if not charge or charge["outstanding"] <= 0 or charge["pending"] > 0:
            continue

        # Determine amount
        if config.amount:
            amount = config.amount
        elif tenant.is_section8 and tenant.tenant_portion:
            amount = tenant.tenant_portion
        elif tenant.current_rent:
            amount = tenant.current_rent
        else:
            logger.warning(f"Autopay skipped for tenant {tenant.id}: no amount configured")
            continue

        amount = min(Decimal(str(amount)), charge["outstanding"])

        result = await initiate_payment(
            tenant_id=tenant.id,
            bank_account_id=config.bank_account_id,
            amount=Decimal(str(amount)),
            payment_month=current_month,
            is_autopay=True,
            charge_id=charge_id,
        )

        if "error" not in result:
            async with get_session() as session:
                ap_result = await session.execute(
                    select(TenantAutopay).where(TenantAutopay.id == config.id)
                )
                ap = ap_result.scalar_one_or_none()
                if ap:
                    ap.last_payment_date = today
                    # Set next payment date to same day next month
                    from dateutil.relativedelta import relativedelta
                    ap.next_payment_date = today + relativedelta(months=1)
            processed += 1
        else:
            logger.error(f"Autopay failed for tenant {tenant.id}: {result['error']}")

    logger.info(f"Autopay run complete: {processed}/{len(autopay_configs)} processed")
    return {"processed": processed, "total": len(autopay_configs)}
