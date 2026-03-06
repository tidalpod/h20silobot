"""Assets / Investment tracking routes"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from database.connection import get_session
from database.models import Property
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["assets"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _dec(v) -> float:
    """Convert Decimal/None to float for arithmetic."""
    if v is None:
        return 0.0
    return float(v)


def _compute_property_metrics(p: Property) -> dict:
    """Compute equity, cash flow, cap rate, LTV for a property."""
    appraised = _dec(p.appraised_value)
    balance = _dec(p.loan_balance)
    rent = _dec(p.monthly_rent)
    piti = _dec(p.monthly_piti)
    hoa = _dec(p.hoa_monthly)

    equity = appraised - balance if p.appraised_value is not None and p.loan_balance is not None else None
    cash_flow = rent - piti - hoa if p.monthly_piti is not None else None
    cap_rate = None
    if p.monthly_piti is not None and appraised > 0:
        annual_cf = (rent - piti - hoa) * 12
        cap_rate = round(annual_cf / appraised * 100, 2)
    ltv = round(balance / appraised * 100, 2) if p.appraised_value and appraised > 0 and p.loan_balance is not None else None

    return {
        "property": p,
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


def _parse_decimal(val: str | None) -> Decimal | None:
    if not val or val.strip() == "":
        return None
    try:
        return Decimal(val.strip().replace(",", ""))
    except InvalidOperation:
        return None


def _parse_date(val: str | None):
    if not val or val.strip() == "":
        return None
    try:
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(val: str | None) -> int | None:
    if not val or val.strip() == "":
        return None
    try:
        return int(val.strip())
    except ValueError:
        return None


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
        prop.loan_amount = _parse_decimal(loan_amount)
        prop.loan_balance = _parse_decimal(loan_balance)
        prop.interest_rate = _parse_decimal(interest_rate)
        prop.loan_term_years = _parse_int(loan_term_years)
        prop.loan_start_date = _parse_date(loan_start_date)
        prop.monthly_pi = _parse_decimal(monthly_pi)
        prop.monthly_tax = _parse_decimal(monthly_tax)
        prop.monthly_insurance = _parse_decimal(monthly_insurance)
        prop.monthly_piti = _parse_decimal(monthly_piti)
        prop.hoa_monthly = _parse_decimal(hoa_monthly)
        prop.rehab_cost = _parse_decimal(rehab_cost)
        prop.updated_at = datetime.utcnow()

    return RedirectResponse(url="/assets", status_code=303)
