"""Tenant Portal — Payment routes (Plaid ACH)"""

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
)
from webapp.auth.tenant_auth import get_current_tenant
from webapp.services import plaid_service, payment_service

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

    return templates.TemplateResponse(
        "portal/pay.html",
        {
            "request": request,
            "tenant": tenant,
            "balance": balance,
            "bank_accounts": bank_accounts,
            "recent_payment": recent_payment,
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
    """Payment history page."""
    tenant, redirect = await _get_tenant_or_redirect(request)
    if redirect:
        return redirect

    async with get_session() as session:
        result = await session.execute(
            select(RentPayment)
            .where(RentPayment.tenant_id == tenant["id"])
            .options(selectinload(RentPayment.property_ref))
            .order_by(desc(RentPayment.initiated_at))
        )
        payments = result.scalars().all()

    return templates.TemplateResponse(
        "portal/pay_history.html",
        {"request": request, "tenant": tenant, "payments": payments},
    )


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
