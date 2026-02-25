"""Payment business logic — balance calculation, payment initiation, autopay, webhooks"""

import logging
from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Tenant, TenantBankAccount, RentPayment, TenantAutopay,
    PaymentStatus, AutopayStatus,
)
from webapp.services import plaid_service

logger = logging.getLogger(__name__)

# Late fee config
GRACE_PERIOD_DAYS = 5
LATE_FEE_PER_DAY = Decimal("15.00")
MAX_PENALTY_DAYS = 5  # $75 max


def calculate_late_fee(for_date: date = None) -> Decimal:
    """Calculate late fee based on current date.

    Rent due on the 1st. 5-day grace period.
    $15/day starting day 6, max 5 penalty days ($75).
    """
    if for_date is None:
        for_date = date.today()

    day = for_date.day
    if day <= GRACE_PERIOD_DAYS:
        return Decimal("0.00")

    penalty_days = min(day - GRACE_PERIOD_DAYS, MAX_PENALTY_DAYS)
    return LATE_FEE_PER_DAY * penalty_days


async def calculate_balance_due(tenant_id: int) -> dict:
    """Calculate total balance due for a tenant including late fees."""
    today = date.today()
    current_month = today.replace(day=1)

    async with get_session() as session:
        result = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .options(selectinload(Tenant.rent_payments))
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        rent_amount = Decimal(str(tenant.current_rent or 0))
        if tenant.is_section8 and tenant.tenant_portion is not None:
            rent_amount = Decimal(str(tenant.tenant_portion))

        # Check if already paid this month
        paid_this_month = False
        for payment in tenant.rent_payments:
            if (payment.payment_month == current_month and
                    payment.status in (PaymentStatus.PENDING, PaymentStatus.PROCESSING, PaymentStatus.COMPLETED)):
                paid_this_month = True
                break

        if paid_this_month:
            return {
                "rent_amount": rent_amount,
                "late_fee": Decimal("0.00"),
                "total_due": Decimal("0.00"),
                "payment_month": current_month,
                "paid": True,
            }

        late_fee = calculate_late_fee(today)

        return {
            "rent_amount": rent_amount,
            "late_fee": late_fee,
            "total_due": rent_amount + late_fee,
            "payment_month": current_month,
            "paid": False,
        }


async def initiate_payment(
    tenant_id: int,
    bank_account_id: int,
    amount: Decimal,
    payment_month: date,
    is_autopay: bool = False,
) -> dict:
    """Create a payment record and initiate Plaid transfer."""
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

        # Calculate late fee
        late_fee = calculate_late_fee()
        total_amount = amount + late_fee

        # Create payment record
        payment = RentPayment(
            tenant_id=tenant_id,
            property_id=tenant.property_id,
            bank_account_id=bank_account_id,
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
        description = f"Rent {payment_month.strftime('%b %Y')}"
        transfer_result = await plaid_service.create_transfer(
            access_token=bank_account.plaid_access_token,
            account_id=bank_account.plaid_account_id,
            amount=str(total_amount),
            description=description,
        )

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


async def process_webhook(data: dict) -> dict:
    """Handle Plaid transfer webhook events."""
    webhook_type = data.get("webhook_type", "")
    webhook_code = data.get("webhook_code", "")

    if webhook_type != "TRANSFER":
        return {"status": "ignored", "reason": f"Not a transfer webhook: {webhook_type}"}

    transfer_id = data.get("transfer_id")
    if not transfer_id:
        return {"status": "ignored", "reason": "No transfer_id"}

    # Get current transfer status from Plaid
    transfer_data = await plaid_service.get_transfer(transfer_id)
    if "error" in transfer_data:
        logger.error(f"Failed to get transfer {transfer_id}: {transfer_data['error']}")
        return {"status": "error", "reason": transfer_data["error"]}

    plaid_status = transfer_data.get("status", "")

    async with get_session() as session:
        result = await session.execute(
            select(RentPayment).where(RentPayment.plaid_transfer_id == transfer_id)
        )
        payment = result.scalar_one_or_none()
        if not payment:
            logger.warning(f"No payment found for transfer {transfer_id}")
            return {"status": "ignored", "reason": "Payment not found"}

        payment.plaid_transfer_status = plaid_status

        if plaid_status in ("settled", "posted"):
            payment.status = PaymentStatus.COMPLETED
            payment.completed_at = datetime.utcnow()
        elif plaid_status == "failed":
            payment.status = PaymentStatus.FAILED
            payment.failed_at = datetime.utcnow()
            payment.failure_reason = transfer_data.get("failure_reason", "Transfer failed")
        elif plaid_status == "returned":
            payment.status = PaymentStatus.RETURNED
            payment.failed_at = datetime.utcnow()
            payment.failure_reason = "Transfer returned by bank"
        elif plaid_status == "cancelled":
            payment.status = PaymentStatus.CANCELLED

        logger.info(f"Payment {payment.id} updated to {payment.status.value} (plaid: {plaid_status})")

    return {"status": "processed", "payment_id": payment.id, "new_status": payment.status.value}


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

        result = await initiate_payment(
            tenant_id=tenant.id,
            bank_account_id=config.bank_account_id,
            amount=Decimal(str(amount)),
            payment_month=current_month,
            is_autopay=True,
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
