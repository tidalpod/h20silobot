"""Tenant Portal — Payment routes (Plaid ACH + Stripe Checkout)"""

from datetime import datetime, date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Tenant, TenantBankAccount, RentPayment, TenantAutopay,
    PaymentStatus, AutopayStatus,
    StripePayment, StripePaymentType, WaterBill, BillStatus,
)
from webapp.auth.tenant_auth import get_current_tenant
from webapp.services import plaid_service, payment_service
from webapp.services import stripe_service
from webapp.config import web_config

router = APIRouter(tags=["portal-payments"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def _get_tenant_or_redirect(request: Request):
    """Get authenticated tenant or return redirect."""
    tenant = await get_current_tenant(request)
    if not tenant:
        return None, RedirectResponse(url="/portal/login", status_code=303)
    return tenant, None


# =============================================================================
# Pay Rent
# =============================================================================

@router.get("/pay", response_class=HTMLResponse)
async def pay_rent_page(request: Request):
    """Pay Rent page — balance due, linked bank, pay button."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    # Get balance due
    balance = await payment_service.calculate_balance_due(tenant["id"])

    # Get linked bank account
    async with get_session() as session:
        bank_result = await session.execute(
            select(TenantBankAccount)
            .where(TenantBankAccount.tenant_id == tenant["id"])
            .where(TenantBankAccount.is_active == True)
            .order_by(desc(TenantBankAccount.linked_at))
        )
        bank_accounts = bank_result.scalars().all()

        # Get recent payment for display
        recent_result = await session.execute(
            select(RentPayment)
            .where(RentPayment.tenant_id == tenant["id"])
            .order_by(desc(RentPayment.initiated_at))
            .limit(1)
        )
        recent_payment = recent_result.scalar_one_or_none()

    # Stripe fee preview
    stripe_fee = None
    if web_config.has_stripe and not balance.get("paid") and balance.get("total_due", 0) > 0:
        stripe_fee = stripe_service.calculate_convenience_fee(balance["total_due"])

    return templates.TemplateResponse(
        "portal/pay.html",
        {
            "request": request,
            "tenant": tenant,
            "balance": balance,
            "bank_accounts": bank_accounts,
            "recent_payment": recent_payment,
            "has_stripe": web_config.has_stripe,
            "stripe_fee": stripe_fee,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/pay", response_class=HTMLResponse)
async def submit_payment(request: Request):
    """Submit one-time payment."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    form = await request.form()
    bank_account_id = int(form.get("bank_account_id", 0))

    if not bank_account_id:
        return RedirectResponse(url="/portal/pay?error=no_bank", status_code=303)

    # Get balance
    balance = await payment_service.calculate_balance_due(tenant["id"])
    if balance.get("paid"):
        return RedirectResponse(url="/portal/pay?error=already_paid", status_code=303)

    result = await payment_service.initiate_payment(
        tenant_id=tenant["id"],
        bank_account_id=bank_account_id,
        amount=balance["rent_amount"],
        payment_month=balance["payment_month"],
    )

    if "error" in result:
        return RedirectResponse(url=f"/portal/pay?error={result['error']}", status_code=303)

    return RedirectResponse(url="/portal/pay?success=1", status_code=303)


# =============================================================================
# Payment History
# =============================================================================

@router.get("/pay/history", response_class=HTMLResponse)
async def payment_history(request: Request):
    """Payment history page — merges ACH and Stripe payments."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    async with get_session() as session:
        # ACH payments
        ach_result = await session.execute(
            select(RentPayment)
            .where(RentPayment.tenant_id == tenant["id"])
            .options(selectinload(RentPayment.property_ref))
            .order_by(desc(RentPayment.initiated_at))
        )
        ach_payments = ach_result.scalars().all()

        # Stripe payments
        stripe_result = await session.execute(
            select(StripePayment)
            .where(StripePayment.tenant_id == tenant["id"])
            .order_by(desc(StripePayment.initiated_at))
        )
        stripe_payments = stripe_result.scalars().all()

    # Merge and sort by date
    all_payments = []
    for p in ach_payments:
        all_payments.append({
            "type": "ach",
            "total_amount": p.total_amount,
            "amount": p.amount,
            "late_fee": p.late_fee,
            "payment_month": p.payment_month,
            "status": p.status,
            "initiated_at": p.initiated_at,
            "is_autopay": p.is_autopay,
            "failure_reason": p.failure_reason,
            "description": f"Rent - {p.payment_month.strftime('%B %Y')}" if p.payment_month else "Rent",
        })
    for p in stripe_payments:
        all_payments.append({
            "type": "card",
            "total_amount": p.total_amount,
            "amount": p.base_amount,
            "late_fee": p.late_fee,
            "convenience_fee": p.convenience_fee,
            "payment_month": p.payment_month,
            "status": p.status,
            "initiated_at": p.initiated_at,
            "is_autopay": False,
            "failure_reason": p.failure_reason,
            "description": p.description,
        })
    all_payments.sort(key=lambda x: x["initiated_at"] or datetime.min, reverse=True)

    return templates.TemplateResponse(
        "portal/pay_history.html",
        {"request": request, "tenant": tenant, "payments": all_payments},
    )


# =============================================================================
# Stripe Checkout
# =============================================================================

@router.post("/pay/stripe")
async def stripe_pay_rent(request: Request):
    """Create Stripe Checkout session for rent payment."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    if not web_config.has_stripe:
        return RedirectResponse(url="/portal/pay?error=stripe_not_configured", status_code=303)

    balance = await payment_service.calculate_balance_due(tenant["id"])
    if balance.get("paid"):
        return RedirectResponse(url="/portal/pay?error=already_paid", status_code=303)

    base_amount = balance["total_due"]
    fee_info = stripe_service.calculate_convenience_fee(base_amount)
    description = f"Rent - {balance['payment_month'].strftime('%B %Y')}"

    # Create StripePayment record
    async with get_session() as session:
        sp = StripePayment(
            tenant_id=tenant["id"],
            property_id=tenant["property_id"],
            payment_type=StripePaymentType.RENT,
            description=description,
            base_amount=fee_info["base_amount"],
            convenience_fee=fee_info["convenience_fee"],
            total_amount=fee_info["total_amount"],
            late_fee=balance.get("late_fee", 0),
            status=PaymentStatus.PENDING,
            payment_month=balance["payment_month"],
        )
        session.add(sp)
        await session.flush()
        sp_id = sp.id

    # Create Checkout Session
    base_url = web_config.site_url.rstrip("/")
    result = stripe_service.create_checkout_session(
        base_amount=fee_info["base_amount"],
        convenience_fee=fee_info["convenience_fee"],
        description=description,
        success_url=f"{base_url}/portal/pay/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/portal/pay?error=cancelled",
        metadata={
            "tenant_id": str(tenant["id"]),
            "payment_type": "rent",
            "stripe_payment_id": str(sp_id),
            "payment_month": balance["payment_month"].isoformat(),
        },
    )

    if "error" in result:
        return RedirectResponse(url=f"/portal/pay?error={result['error']}", status_code=303)

    # Save session ID
    async with get_session() as session:
        sp_result = await session.execute(
            select(StripePayment).where(StripePayment.id == sp_id)
        )
        sp = sp_result.scalar_one()
        sp.stripe_checkout_session_id = result["session_id"]

    return RedirectResponse(url=result["url"], status_code=303)


@router.get("/pay/stripe/success", response_class=HTMLResponse)
async def stripe_success(request: Request):
    """Success landing page after Stripe Checkout redirect."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    session_id = request.query_params.get("session_id")
    payment_info = None
    if session_id:
        payment_info = stripe_service.retrieve_session(session_id)

    return templates.TemplateResponse(
        "portal/pay_stripe_success.html",
        {
            "request": request,
            "tenant": tenant,
            "payment_info": payment_info,
            "session_id": session_id,
        },
    )


@router.post("/bills/pay")
async def stripe_pay_bill(request: Request):
    """Create Stripe Checkout session for a water bill."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    if not web_config.has_stripe:
        return RedirectResponse(url="/portal/bills?error=stripe_not_configured", status_code=303)

    form = await request.form()
    bill_id = int(form.get("bill_id", 0))
    if not bill_id:
        return RedirectResponse(url="/portal/bills?error=no_bill", status_code=303)

    # Fetch the bill
    async with get_session() as session:
        bill_result = await session.execute(
            select(WaterBill).where(
                WaterBill.id == bill_id,
                WaterBill.property_id == tenant["property_id"],
            )
        )
        bill = bill_result.scalar_one_or_none()

    if not bill or not bill.amount_due or bill.amount_due <= 0:
        return RedirectResponse(url="/portal/bills?error=invalid_bill", status_code=303)

    base_amount = Decimal(str(bill.amount_due))
    fee_info = stripe_service.calculate_convenience_fee(base_amount)
    month_label = bill.statement_date.strftime("%b %Y") if bill.statement_date else "Water Bill"
    description = f"Water Bill - {month_label}"

    # Create StripePayment record
    async with get_session() as session:
        sp = StripePayment(
            tenant_id=tenant["id"],
            property_id=tenant["property_id"],
            payment_type=StripePaymentType.WATER_BILL,
            reference_id=bill_id,
            description=description,
            base_amount=fee_info["base_amount"],
            convenience_fee=fee_info["convenience_fee"],
            total_amount=fee_info["total_amount"],
            status=PaymentStatus.PENDING,
        )
        session.add(sp)
        await session.flush()
        sp_id = sp.id

    base_url = web_config.site_url.rstrip("/")
    result = stripe_service.create_checkout_session(
        base_amount=fee_info["base_amount"],
        convenience_fee=fee_info["convenience_fee"],
        description=description,
        success_url=f"{base_url}/portal/pay/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/portal/bills",
        metadata={
            "tenant_id": str(tenant["id"]),
            "payment_type": "water_bill",
            "stripe_payment_id": str(sp_id),
            "bill_id": str(bill_id),
        },
    )

    if "error" in result:
        return RedirectResponse(url=f"/portal/bills?error={result['error']}", status_code=303)

    async with get_session() as session:
        sp_result = await session.execute(
            select(StripePayment).where(StripePayment.id == sp_id)
        )
        sp = sp_result.scalar_one()
        sp.stripe_checkout_session_id = result["session_id"]

    return RedirectResponse(url=result["url"], status_code=303)


@router.get("/pay/deposit", response_class=HTMLResponse)
async def pay_deposit_page(request: Request):
    """Security deposit payment page."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    if not web_config.has_stripe:
        return RedirectResponse(url="/portal", status_code=303)

    return templates.TemplateResponse(
        "portal/pay_deposit.html",
        {
            "request": request,
            "tenant": tenant,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/pay/deposit")
async def stripe_pay_deposit(request: Request):
    """Create Stripe Checkout session for security deposit."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    if not web_config.has_stripe:
        return RedirectResponse(url="/portal?error=stripe_not_configured", status_code=303)

    form = await request.form()
    try:
        amount = Decimal(form.get("amount", "0"))
    except Exception:
        return RedirectResponse(url="/portal/pay/deposit?error=invalid_amount", status_code=303)

    if amount <= 0:
        return RedirectResponse(url="/portal/pay/deposit?error=invalid_amount", status_code=303)

    fee_info = stripe_service.calculate_convenience_fee(amount)
    description = "Security Deposit"

    async with get_session() as session:
        sp = StripePayment(
            tenant_id=tenant["id"],
            property_id=tenant["property_id"],
            payment_type=StripePaymentType.SECURITY_DEPOSIT,
            description=description,
            base_amount=fee_info["base_amount"],
            convenience_fee=fee_info["convenience_fee"],
            total_amount=fee_info["total_amount"],
            status=PaymentStatus.PENDING,
        )
        session.add(sp)
        await session.flush()
        sp_id = sp.id

    base_url = web_config.site_url.rstrip("/")
    result = stripe_service.create_checkout_session(
        base_amount=fee_info["base_amount"],
        convenience_fee=fee_info["convenience_fee"],
        description=description,
        success_url=f"{base_url}/portal/pay/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/portal/pay/deposit?error=cancelled",
        metadata={
            "tenant_id": str(tenant["id"]),
            "payment_type": "security_deposit",
            "stripe_payment_id": str(sp_id),
        },
    )

    if "error" in result:
        return RedirectResponse(url=f"/portal/pay/deposit?error={result['error']}", status_code=303)

    async with get_session() as session:
        sp_result = await session.execute(
            select(StripePayment).where(StripePayment.id == sp_id)
        )
        sp = sp_result.scalar_one()
        sp.stripe_checkout_session_id = result["session_id"]

    return RedirectResponse(url=result["url"], status_code=303)


@router.get("/pay/stripe/fee-preview")
async def stripe_fee_preview(request: Request):
    """JSON endpoint for JS fee calculation."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    try:
        amount = Decimal(request.query_params.get("amount", "0"))
    except Exception:
        return JSONResponse({"error": "Invalid amount"}, status_code=400)

    if amount <= 0:
        return JSONResponse({"error": "Amount must be positive"}, status_code=400)

    fee_info = stripe_service.calculate_convenience_fee(amount)
    return JSONResponse({
        "base_amount": str(fee_info["base_amount"]),
        "convenience_fee": str(fee_info["convenience_fee"]),
        "total_amount": str(fee_info["total_amount"]),
    })


# =============================================================================
# Bank Account Management
# =============================================================================

@router.get("/pay/bank", response_class=HTMLResponse)
async def bank_management(request: Request):
    """Bank account management page."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    async with get_session() as session:
        result = await session.execute(
            select(TenantBankAccount)
            .where(TenantBankAccount.tenant_id == tenant["id"])
            .order_by(desc(TenantBankAccount.linked_at))
        )
        bank_accounts = result.scalars().all()

    return templates.TemplateResponse(
        "portal/pay_bank.html",
        {
            "request": request,
            "tenant": tenant,
            "bank_accounts": bank_accounts,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/pay/bank/link-token")
async def get_link_token(request: Request):
    """JSON: Get Plaid Link token for widget."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    result = await plaid_service.create_link_token(
        tenant_id=tenant["id"],
        tenant_name=tenant["name"],
    )
    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=400)

    return JSONResponse({"link_token": result["link_token"]})


@router.post("/pay/bank/link-complete")
async def link_complete(request: Request):
    """JSON: Handle public_token from Plaid Link."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    data = await request.json()
    public_token = data.get("public_token")
    if not public_token:
        return JSONResponse({"error": "Missing public_token"}, status_code=400)

    # Exchange public token
    exchange = await plaid_service.exchange_public_token(public_token)
    if "error" in exchange:
        return JSONResponse({"error": exchange["error"]}, status_code=400)

    access_token = exchange["access_token"]
    item_id = exchange["item_id"]

    # Get account info
    accounts_data = await plaid_service.get_accounts(access_token)
    if "error" in accounts_data:
        return JSONResponse({"error": accounts_data["error"]}, status_code=400)

    accounts = accounts_data.get("accounts", [])
    institution_name = accounts_data.get("institution_name", "")

    if not accounts:
        return JSONResponse({"error": "No accounts found"}, status_code=400)

    # Use first checking/savings account
    account = accounts[0]
    for a in accounts:
        if a.get("subtype") in ("checking", "savings"):
            account = a
            break

    async with get_session() as session:
        bank_account = TenantBankAccount(
            tenant_id=tenant["id"],
            plaid_access_token=access_token,
            plaid_item_id=item_id,
            plaid_account_id=account["account_id"],
            account_name=account.get("name") or account.get("official_name", "Account"),
            account_mask=account.get("mask", ""),
            institution_name=institution_name,
            is_active=True,
        )
        session.add(bank_account)

    return JSONResponse({"success": True, "account_mask": account.get("mask", "")})


@router.post("/pay/bank/unlink")
async def unlink_bank(request: Request):
    """Unlink bank account."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    form = await request.form()
    account_id = int(form.get("account_id", 0))

    async with get_session() as session:
        result = await session.execute(
            select(TenantBankAccount)
            .where(TenantBankAccount.id == account_id)
            .where(TenantBankAccount.tenant_id == tenant["id"])
        )
        account = result.scalar_one_or_none()
        if account:
            # Remove from Plaid
            await plaid_service.remove_item(account.plaid_access_token)
            account.is_active = False

    return RedirectResponse(url="/portal/pay/bank?success=unlinked", status_code=303)


# =============================================================================
# Autopay
# =============================================================================

@router.get("/pay/autopay", response_class=HTMLResponse)
async def autopay_settings(request: Request):
    """Autopay settings page."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    async with get_session() as session:
        # Get autopay config
        ap_result = await session.execute(
            select(TenantAutopay)
            .where(TenantAutopay.tenant_id == tenant["id"])
            .options(selectinload(TenantAutopay.bank_account_ref))
        )
        autopay = ap_result.scalar_one_or_none()

        # Get active bank accounts
        bank_result = await session.execute(
            select(TenantBankAccount)
            .where(TenantBankAccount.tenant_id == tenant["id"])
            .where(TenantBankAccount.is_active == True)
        )
        bank_accounts = bank_result.scalars().all()

    return templates.TemplateResponse(
        "portal/pay_autopay.html",
        {
            "request": request,
            "tenant": tenant,
            "autopay": autopay,
            "bank_accounts": bank_accounts,
            "success": request.query_params.get("success"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/pay/autopay")
async def update_autopay(request: Request):
    """Enable/update/disable autopay."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    form = await request.form()
    action = form.get("action", "enable")

    async with get_session() as session:
        ap_result = await session.execute(
            select(TenantAutopay).where(TenantAutopay.tenant_id == tenant["id"])
        )
        autopay = ap_result.scalar_one_or_none()

        if action == "disable":
            if autopay:
                autopay.status = AutopayStatus.CANCELLED
            return RedirectResponse(url="/portal/pay/autopay?success=disabled", status_code=303)

        # Enable or update
        bank_account_id = int(form.get("bank_account_id", 0))
        pay_day = int(form.get("pay_day", 1))

        if not bank_account_id:
            return RedirectResponse(url="/portal/pay/autopay?error=no_bank", status_code=303)

        if pay_day < 1 or pay_day > 28:
            pay_day = 1

        if autopay:
            autopay.bank_account_id = bank_account_id
            autopay.pay_day = pay_day
            autopay.status = AutopayStatus.ACTIVE
            autopay.updated_at = datetime.utcnow()
        else:
            # Calculate next payment date
            today = date.today()
            if today.day <= pay_day:
                next_date = today.replace(day=pay_day)
            else:
                from dateutil.relativedelta import relativedelta
                next_date = (today + relativedelta(months=1)).replace(day=pay_day)

            autopay = TenantAutopay(
                tenant_id=tenant["id"],
                bank_account_id=bank_account_id,
                pay_day=pay_day,
                status=AutopayStatus.ACTIVE,
                next_payment_date=next_date,
            )
            session.add(autopay)

    return RedirectResponse(url="/portal/pay/autopay?success=enabled", status_code=303)
