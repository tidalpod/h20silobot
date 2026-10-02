"""Assets / Investment tracking routes"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
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

ASSET_SORT_KEYS = (
    "property",
    "purchase",
    "rehab",
    "appraised",
    "equity",
    "loan_balance",
    "servicer",
    "rate",
    "piti",
    "rent",
    "cash_flow",
    "cap_rate",
    "ltv",
)

# These addresses are represented as one Property record per apartment in the
# operating system, but are one physical asset for valuation and financing.
# Keep the rollup explicit so similarly named single-family homes are never
# merged by a broad address heuristic.
MULTIUNIT_ASSET_ADDRESSES = {
    "11035 republic ave": "11035 Republic Ave",
    "3616 wasmund ave": "3616 Wasmund Ave",
}


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


def _normalized_asset_address(address: str) -> str:
    """Normalize an address just enough to identify configured multi-unit assets."""
    return " ".join(
        (address or "")
        .casefold()
        .replace(".", " ")
        .replace(",", " ")
        .split()
    )


def _asset_rollup_key(p: Property) -> str:
    """Return a stable building key for configured duplexes, else the property id."""
    normalized = _normalized_asset_address(p.address)
    for base in MULTIUNIT_ASSET_ADDRESSES:
        if normalized == base or normalized.startswith(f"{base} apt ") or normalized.startswith(f"{base} unit "):
            return f"building:{base}"
    return f"property:{p.id}"


def _rollup_property_order(p: Property):
    """Prefer Unit/Apt 1 as the canonical record for shared asset data."""
    normalized = _normalized_asset_address(p.address)
    is_unit_one = normalized.endswith(" apt 1") or normalized.endswith(" unit 1")
    return (0 if is_unit_one else 1, normalized, p.id or 0)


def _first_property_value(properties: list[Property], field: str):
    """Return the canonical non-empty shared value without adding duplicates."""
    for prop in properties:
        value = getattr(prop, field)
        if value is not None:
            return value
    return None


def _compute_asset_rollup(properties: list[Property]) -> dict:
    """Compute one Assets-table row for one physical building."""
    ordered = sorted(properties, key=_rollup_property_order)
    primary = ordered[0]
    loan = primary.current_loan or next((prop.current_loan for prop in ordered if prop.current_loan), None)

    rents = [(prop, _effective_monthly_rent(prop)) for prop in ordered]
    populated_rents = [Decimal(rent) for _, rent in rents if rent is not None]
    rent_value = sum(populated_rents, Decimal("0")) if populated_rents else None

    purchase_price = _first_property_value(ordered, "purchase_price")
    purchase_date = _first_property_value(ordered, "purchase_date")
    rehab_cost = _first_property_value(ordered, "rehab_cost")
    appraised_value = _first_property_value(ordered, "appraised_value")
    appraisal_date = _first_property_value(ordered, "appraisal_date")
    monthly_tax = _first_property_value(ordered, "monthly_tax")
    legacy_balance = _first_property_value(ordered, "loan_balance")
    legacy_payment = _first_property_value(ordered, "monthly_piti")
    legacy_rate = _first_property_value(ordered, "interest_rate")
    hoa_value = _first_property_value(ordered, "hoa_monthly")

    balance_value = loan.current_balance if loan else legacy_balance
    payment_value = loan.monthly_payment if loan else legacy_payment
    rate_value = loan.interest_rate if loan else legacy_rate
    appraised = _dec(appraised_value)
    balance = _dec(balance_value)
    rent = _dec(rent_value)
    piti = _dec(payment_value)
    hoa = _dec(hoa_value)

    equity = appraised - balance if appraised_value is not None and balance_value is not None else None
    # Until tax and insurance expense tracking is added, a debt-free asset's
    # cash-flow figure is its gross scheduled rent. Mortgaged assets continue
    # to show rent less PITI and HOA.
    cash_flow = rent - piti - hoa if payment_value is not None else rent_value
    cap_rate = None
    if payment_value is not None and appraised > 0:
        cap_rate = round(((rent - piti - hoa) * 12) / appraised * 100, 2)
    ltv = round(balance / appraised * 100, 2) if appraised_value is not None and appraised > 0 and balance_value is not None else None

    normalized_primary = _normalized_asset_address(primary.address)
    display_address = primary.address
    for base, label in MULTIUNIT_ASSET_ADDRESSES.items():
        if normalized_primary == base or normalized_primary.startswith(f"{base} apt ") or normalized_primary.startswith(f"{base} unit "):
            display_address = label
            break

    return {
        "property": primary,
        "properties": ordered,
        "loan": loan,
        "display_address": display_address,
        "unit_count": len(ordered),
        "rent_components": rents,
        "purchase_price": purchase_price,
        "purchase_date": purchase_date,
        "rehab_cost": rehab_cost,
        "appraised_value": appraised_value,
        "appraisal_date": appraisal_date,
        "monthly_tax": monthly_tax,
        "hoa_monthly": hoa_value,
        "loan_balance": balance_value,
        "interest_rate": rate_value,
        "monthly_payment": payment_value,
        "monthly_rent": rent_value,
        "equity": equity,
        "cash_flow": cash_flow,
        "cap_rate": cap_rate,
        "ltv": ltv,
    }


def _compute_property_metrics(p: Property) -> dict:
    """Compute equity, cash flow, cap rate, LTV for a property."""
    return _compute_asset_rollup([p])


def _build_asset_rows(properties: list[Property]) -> list[dict]:
    """Collapse configured multi-unit records into physical-asset rows."""
    rollups: dict[tuple[str, str], list[Property]] = {}
    for prop in properties:
        entity = prop.entity or "Unassigned"
        rollups.setdefault((entity, _asset_rollup_key(prop)), []).append(prop)
    return [_compute_asset_rollup(group) for group in rollups.values()]


def _asset_sort_value(row: dict, key: str):
    """Return the normalized value used to sort an Assets table row."""
    loan = row["loan"]
    values = {
        "property": row["display_address"].casefold(),
        "purchase": row["purchase_price"],
        "rehab": row["rehab_cost"],
        "appraised": row["appraised_value"],
        "equity": row["equity"],
        "loan_balance": row["loan_balance"],
        "servicer": loan.servicer.casefold() if loan and loan.servicer else None,
        "rate": row["interest_rate"],
        "piti": row["monthly_payment"],
        "rent": row["monthly_rent"],
        "cash_flow": row["cash_flow"],
        "cap_rate": row["cap_rate"],
        "ltv": row["ltv"],
    }
    return values[key]


@router.get("/", response_class=HTMLResponse)
async def assets_dashboard(request: Request, sort: str = "property", direction: str = "asc"):
    """Portfolio-level investment dashboard."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if sort not in ASSET_SORT_KEYS:
        sort = "property"
    if direction not in {"asc", "desc"}:
        direction = "asc"

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .options(selectinload(Property.loans), selectinload(Property.tenants))
            .where(Property.is_active == True)
            .order_by(Property.entity, Property.address)
        )
        all_properties = result.scalars().all()

    # Build one metrics row per physical asset. Configured duplex unit records
    # are consolidated here before grouping, sorting, and portfolio totals.
    rows = _build_asset_rows(all_properties)

    # Group by entity
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        entity = row["property"].entity or "Unassigned"
        grouped.setdefault(entity, []).append(row)

    # Keep ownership groups intact while sorting properties within each group.
    for entity, entity_rows in grouped.items():
        populated = [row for row in entity_rows if _asset_sort_value(row, sort) is not None]
        empty = [row for row in entity_rows if _asset_sort_value(row, sort) is None]
        grouped[entity] = sorted(
            populated,
            key=lambda row: _asset_sort_value(row, sort),
            reverse=direction == "desc",
        ) + empty

    sort_urls = {}
    for key in ASSET_SORT_KEYS:
        next_direction = "desc" if sort == key and direction == "asc" else "asc"
        sort_urls[key] = f"/assets/?sort={key}&direction={next_direction}"

    # Portfolio totals
    total_value = sum(_dec(r["appraised_value"]) for r in rows)
    total_equity = sum(_dec(r["equity"]) for r in rows)
    total_debt = sum(_dec(r["loan_balance"]) for r in rows)
    total_cash_flow = sum(_dec(r["cash_flow"]) for r in rows)
    total_rehab = sum(_dec(r["rehab_cost"]) for r in rows)

    return templates.TemplateResponse("assets/dashboard.html", {
        "request": request,
        "user": request.session.get("user"),
        "grouped": grouped,
        "total_value": total_value,
        "total_equity": total_equity,
        "total_debt": total_debt,
        "total_cash_flow": total_cash_flow,
        "total_rehab": total_rehab,
        "sort_key": sort,
        "sort_direction": direction,
        "sort_urls": sort_urls,
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


ASSET_LOAN_FIELDS = (
    "loan_number_last4",
    "servicer",
    "original_amount",
    "current_balance",
    "interest_rate",
    "loan_type",
    "term_months",
    "start_date",
    "maturity_date",
    "monthly_payment",
    "escrow_balance",
    "status",
    "notes",
    "is_current",
)


def _validated_asset_loan_payload(form: dict) -> dict:
    """Validate the active-loan fields exposed by the Assets pencil modal.

    Insurance fields intentionally remain on the full Loan tab. Filtering the
    normalized payload prevents a quick Assets edit from clearing those values.
    """
    loan_form = {
        "loan_number_last4": form.get("loan_number_last4"),
        "servicer": form.get("loan_servicer"),
        "original_amount": form.get("loan_original_amount"),
        "current_balance": form.get("loan_current_balance"),
        "interest_rate": form.get("loan_interest_rate"),
        "loan_type": form.get("loan_type"),
        "term_years": form.get("loan_term_years"),
        "start_date": form.get("loan_start_date"),
        "maturity_date": form.get("loan_maturity_date"),
        "monthly_payment": form.get("loan_monthly_payment"),
        "escrow_balance": form.get("loan_escrow_balance"),
        "status": form.get("loan_status"),
        "notes": form.get("loan_notes"),
        "is_current": "1",
    }
    payload = _validated_loan_payload(loan_form)
    return {field: payload[field] for field in ASSET_LOAN_FIELDS}


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
):
    """Save property values and, when present, the current loan snapshot."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = dict(await request.form())
    raw_loan_id = (form.get("loan_id") or "").strip()
    loan_id = _parse_int(raw_loan_id)
    if raw_loan_id and loan_id is None:
        return RedirectResponse(url="/assets?edit_error=invalid_loan", status_code=303)

    loan_payload = None
    if loan_id is not None:
        try:
            loan_payload = _validated_asset_loan_payload(form)
        except ValueError as exc:
            return RedirectResponse(url=f"/assets?edit_error={exc}", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.id == property_id)
            .options(selectinload(Property.loans))
        )
        prop = result.scalar_one_or_none()
        if not prop:
            return RedirectResponse(url="/assets", status_code=303)

        loan = None
        if loan_id is not None and loan_payload is not None:
            loan = next((item for item in prop.loans if item.id == loan_id and item.is_current), None)
            if loan is None:
                return RedirectResponse(url="/assets?edit_error=loan_not_found", status_code=303)

            last4 = loan_payload["loan_number_last4"]
            if last4 and any(
                item.id != loan.id and item.loan_number_last4 == last4
                for item in prop.loans
            ):
                return RedirectResponse(url="/assets?edit_error=duplicate_loan", status_code=303)

        prop.purchase_price = _parse_decimal(form.get("purchase_price"))
        prop.purchase_date = _parse_date(form.get("purchase_date"))
        prop.appraised_value = _parse_decimal(form.get("appraised_value"))
        prop.appraisal_date = _parse_date(form.get("appraisal_date"))
        prop.monthly_tax = _parse_decimal(form.get("monthly_tax"))
        prop.hoa_monthly = _parse_decimal(form.get("hoa_monthly"))
        prop.rehab_cost = _parse_decimal(form.get("rehab_cost"))

        if loan is not None and loan_payload is not None:
            for existing in prop.loans:
                existing.is_current = existing is loan
            for field, value in loan_payload.items():
                setattr(loan, field, value)
            loan.updated_at = datetime.utcnow()
            _sync_property_loan_snapshot(prop, loan)

        prop.updated_at = datetime.utcnow()

    return RedirectResponse(url=f"/assets?asset_saved={property_id}", status_code=303)


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
