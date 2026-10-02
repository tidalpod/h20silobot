"""Assets / Investment tracking routes"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, PropertyLoan
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["assets"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _dec(v) -> float:
    """Convert Decimal/None to float for arithmetic."""
    if v is None:
        return 0.0
    return float(v)


def _effective_monthly_rent(p: Property):
    """Return the rent already maintained for the property's active household."""
    active_tenants = [tenant for tenant in p.tenants if tenant.is_active]
    primary_tenant = next((tenant for tenant in active_tenants if tenant.is_primary), None)
    tenant = primary_tenant or (active_tenants[0] if active_tenants else None)

    if tenant:
        if tenant.is_section8 and (tenant.voucher_amount is not None or tenant.tenant_portion is not None):
            return Decimal(tenant.voucher_amount or 0) + Decimal(tenant.tenant_portion or 0)
        if tenant.current_rent is not None:
            return Decimal(tenant.current_rent)

    # Keep the advertised property rent as a fallback for vacant/listed units.
    return p.monthly_rent


def _compute_property_metrics(p: Property) -> dict:
    """Compute equity, cash flow, cap rate, LTV for a property."""
    loan = p.current_loan
    appraised = _dec(p.appraised_value)
    balance_value = loan.current_balance if loan else p.loan_balance
    payment_value = loan.monthly_payment if loan else p.monthly_piti
    balance = _dec(balance_value)
    rent_value = _effective_monthly_rent(p)
    rent = _dec(rent_value)
    piti = _dec(payment_value)
    hoa = _dec(p.hoa_monthly)

    equity = appraised - balance if p.appraised_value is not None and balance_value is not None else None
    cash_flow = rent - piti - hoa if payment_value is not None else None
    cap_rate = None
    if payment_value is not None and appraised > 0:
        annual_cf = (rent - piti - hoa) * 12
        cap_rate = round(annual_cf / appraised * 100, 2)
    ltv = round(balance / appraised * 100, 2) if p.appraised_value and appraised > 0 and balance_value is not None else None

    return {
        "property": p,
        "loan": loan,
        "monthly_rent": rent_value,
        "equity": equity,
        "cash_flow": cash_flow,
        "cap_rate": cap_rate,
        "ltv": ltv,
    }


@router.get("/", response_class=HTMLResponse)
async def assets_dashboard(request: Request):
    """Portfolio-level investment dashboard."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .options(selectinload(Property.loans), selectinload(Property.tenants))
            .where(Property.is_active == True)
            .order_by(Property.entity, Property.address)
        )
        all_properties = result.scalars().all()

    # Build per-property metrics
    rows = [_compute_property_metrics(p) for p in all_properties]

    # Group by entity
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        entity = row["property"].entity or "Unassigned"
        grouped.setdefault(entity, []).append(row)

    # Portfolio totals
    total_value = sum(_dec(r["property"].appraised_value) for r in rows)
    total_equity = sum(_dec(r["equity"]) for r in rows)
    total_debt = sum(_dec(r["property"].loan_balance) for r in rows)
    total_cash_flow = sum(_dec(r["cash_flow"]) for r in rows)
    total_rehab = sum(_dec(r["property"].rehab_cost) for r in rows)

    return templates.TemplateResponse("assets/dashboard.html", {
        "request": request,
        "user": request.session.get("user"),
        "grouped": grouped,
        "total_value": total_value,
        "total_equity": total_equity,
        "total_debt": total_debt,
        "total_cash_flow": total_cash_flow,
        "total_rehab": total_rehab,
    })


def _parse_decimal(val: Optional[str]) -> Optional[Decimal]:
    if not val or val.strip() == "":
        return None
    try:
        return Decimal(val.strip().replace(",", ""))
    except InvalidOperation:
        return None


def _parse_date(val: Optional[str]):
    if not val or val.strip() == "":
        return None
    try:
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(val: Optional[str]) -> Optional[int]:
    if not val or val.strip() == "":
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


LOAN_STATUSES = {"active", "transferred", "paid_off", "unknown"}
PREMIUM_FREQUENCIES = {"monthly", "annual"}


def _parse_bounded_text(value: Optional[str], max_length: int) -> Optional[str]:
    text_value = (value or "").strip()
    if not text_value:
        return None
    if len(text_value) > max_length:
        raise ValueError("text_too_long")
    return text_value


def _parse_loan_decimal(value: Optional[str], field: str, *, allow_negative: bool = False):
    parsed = _parse_decimal(value)
    if value is not None and str(value).strip() and parsed is None:
        raise ValueError(f"invalid_{field}")
    if parsed is not None and not allow_negative and parsed < 0:
        raise ValueError(f"invalid_{field}")
    return parsed


def _validated_loan_payload(form: dict) -> dict:
    """Validate and normalize financing form input without logging identifiers."""
    last4 = (form.get("loan_number_last4") or "").strip() or None
    if last4 and (len(last4) != 4 or not last4.isdigit()):
        raise ValueError("invalid_loan_number")

    rate = _parse_loan_decimal(form.get("interest_rate"), "interest_rate")
    if rate is not None and rate > 100:
        raise ValueError("invalid_interest_rate")

    term_years = _parse_int(form.get("term_years"))
    if form.get("term_years") and term_years is None:
        raise ValueError("invalid_term")
    if term_years is not None and not 1 <= term_years <= 100:
        raise ValueError("invalid_term")

    start_date = _parse_date(form.get("start_date"))
    maturity_date = _parse_date(form.get("maturity_date"))
    if form.get("start_date") and start_date is None:
        raise ValueError("invalid_start_date")
    if form.get("maturity_date") and maturity_date is None:
        raise ValueError("invalid_maturity_date")
    if start_date and maturity_date and maturity_date < start_date:
        raise ValueError("invalid_date_range")

    expiration = _parse_date(form.get("insurance_expiration_date"))
    if form.get("insurance_expiration_date") and expiration is None:
        raise ValueError("invalid_insurance_expiration")

    status = (form.get("status") or "active").strip().lower()
    if status not in LOAN_STATUSES:
        raise ValueError("invalid_status")

    premium_frequency = (form.get("insurance_premium_frequency") or "").strip().lower() or None
    if premium_frequency and premium_frequency not in PREMIUM_FREQUENCIES:
        raise ValueError("invalid_premium_frequency")

    return {
        "loan_number_last4": last4,
        "servicer": _parse_bounded_text(form.get("servicer"), 255),
        "original_amount": _parse_loan_decimal(form.get("original_amount"), "original_amount"),
        "current_balance": _parse_loan_decimal(form.get("current_balance"), "current_balance"),
        "interest_rate": rate,
        "loan_type": _parse_bounded_text(form.get("loan_type"), 100),
        "term_months": term_years * 12 if term_years is not None else None,
        "start_date": start_date,
        "maturity_date": maturity_date,
        "monthly_payment": _parse_loan_decimal(form.get("monthly_payment"), "monthly_payment"),
        "escrow_balance": _parse_loan_decimal(form.get("escrow_balance"), "escrow_balance", allow_negative=True),
        "insurance_carrier": _parse_bounded_text(form.get("insurance_carrier"), 255),
        "insurance_payee": _parse_bounded_text(form.get("insurance_payee"), 255),
        "insurance_policy_number": _parse_bounded_text(form.get("insurance_policy_number"), 100),
        "insurance_expiration_date": expiration,
        "insurance_premium": _parse_loan_decimal(form.get("insurance_premium"), "insurance_premium"),
        "insurance_premium_frequency": premium_frequency,
        "status": status,
        "notes": _parse_bounded_text(form.get("notes"), 2000),
        "is_current": str(form.get("is_current") or "").lower() in {"1", "true", "on", "yes"},
    }


def _sync_property_loan_snapshot(prop: Property, loan: PropertyLoan):
    """Keep legacy Assets metrics aligned with the current related loan."""
    prop.loan_amount = loan.original_amount
    prop.loan_balance = loan.current_balance
    prop.interest_rate = loan.interest_rate
    prop.loan_term_years = int(loan.term_months / 12) if loan.term_months else None
    prop.loan_start_date = loan.start_date
    prop.monthly_piti = loan.monthly_payment
    if loan.insurance_premium is None:
        prop.monthly_insurance = None
    elif loan.insurance_premium_frequency == "annual":
        prop.monthly_insurance = (loan.insurance_premium / Decimal("12")).quantize(Decimal("0.01"))
    else:
        prop.monthly_insurance = loan.insurance_premium


@router.post("/{property_id}/edit", response_class=HTMLResponse)
async def save_financial_data(
    request: Request,
    property_id: int,
    purchase_price: str = Form(None),
    purchase_date: str = Form(None),
    appraised_value: str = Form(None),
    appraisal_date: str = Form(None),
    loan_amount: str = Form(None),
    loan_balance: str = Form(None),
    interest_rate: str = Form(None),
    loan_term_years: str = Form(None),
    loan_start_date: str = Form(None),
    monthly_pi: str = Form(None),
    monthly_tax: str = Form(None),
    monthly_insurance: str = Form(None),
    monthly_piti: str = Form(None),
    hoa_monthly: str = Form(None),
    rehab_cost: str = Form(None),
):
    """Save financial data for a single property."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if not prop:
            return RedirectResponse(url="/assets", status_code=303)

        prop.purchase_price = _parse_decimal(purchase_price)
        prop.purchase_date = _parse_date(purchase_date)
        prop.appraised_value = _parse_decimal(appraised_value)
        prop.appraisal_date = _parse_date(appraisal_date)
        prop.monthly_tax = _parse_decimal(monthly_tax)
        prop.hoa_monthly = _parse_decimal(hoa_monthly)
        prop.rehab_cost = _parse_decimal(rehab_cost)
        prop.updated_at = datetime.utcnow()

    return RedirectResponse(url="/assets", status_code=303)


@router.post("/{property_id}/loans/save", response_class=HTMLResponse)
async def save_property_loan(request: Request, property_id: int):
    """Create or update a property's current financing record."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = dict(await request.form())
    try:
        payload = _validated_loan_payload(form)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/properties/{property_id}?tab=loan&loan_error={exc}",
            status_code=303,
        )

    loan_id = _parse_int(form.get("loan_id"))
    async with get_session() as session:
        prop_result = await session.execute(
            select(Property)
            .where(Property.id == property_id)
            .options(selectinload(Property.loans))
        )
        prop = prop_result.scalar_one_or_none()
        if not prop:
            return RedirectResponse(url="/assets", status_code=303)

        loan = None
        if loan_id:
            loan = next((item for item in prop.loans if item.id == loan_id), None)
            if loan is None:
                return RedirectResponse(
                    url=f"/properties/{property_id}?tab=loan&loan_error=loan_not_found",
                    status_code=303,
                )

        last4 = payload["loan_number_last4"]
        if last4:
            duplicate = next(
                (
                    item for item in prop.loans
                    if item.loan_number_last4 == last4 and (loan is None or item.id != loan.id)
                ),
                None,
            )
            if duplicate:
                return RedirectResponse(
                    url=f"/properties/{property_id}?tab=loan&loan_error=duplicate_loan",
                    status_code=303,
                )

        if loan is None:
            loan = PropertyLoan(property_id=property_id)
            session.add(loan)

        if payload["is_current"]:
            for existing in prop.loans:
                if existing is not loan:
                    existing.is_current = False

        for field, value in payload.items():
            setattr(loan, field, value)
        loan.updated_at = datetime.utcnow()

        if loan.is_current:
            _sync_property_loan_snapshot(prop, loan)
            prop.updated_at = datetime.utcnow()

    return RedirectResponse(
        url=f"/properties/{property_id}?tab=loan&loan_saved=1",
        status_code=303,
    )
