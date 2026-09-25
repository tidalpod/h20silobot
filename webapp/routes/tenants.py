"""Tenant management routes"""

from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Tenant, Property, PHA, RentPayment, StripePayment,
    WorkOrder, WorkOrderStatus, LeaseDocument, LeaseStatus,
    WaterBill, TenantBankAccount, TenantAutopay, PaymentStatus,
    ExternalPayment,
)
from webapp.auth.dependencies import get_current_user
from webapp.services import ledger_service
from decimal import Decimal

router = APIRouter(tags=["tenants"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_tenants(
    request: Request,
    property_id: str = "",
    active_only: bool = True,
    tenant_search: str = "",
    page: int = 1,
    page_size: int = 25,
):
    """List all tenants"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    tenant_search = tenant_search.strip()[:100]
    page = max(page, 1)
    page_size = page_size if page_size in {25, 50, 100} else 25
    try:
        selected_property_id = int(property_id) if property_id.strip() else None
    except (TypeError, ValueError):
        selected_property_id = None

    async with get_session() as session:
        conditions = []

        if tenant_search:
            escaped_search = (
                tenant_search
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            conditions.append(
                Tenant.name.ilike(f"%{escaped_search}%", escape="\\")
            )

        if selected_property_id:
            conditions.append(Tenant.property_id == selected_property_id)

        if active_only:
            conditions.append(Tenant.is_active == True)

        count_result = await session.execute(
            select(func.count(Tenant.id)).where(*conditions)
        )
        total_items = count_result.scalar() or 0
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(page, total_pages)

        query = (
            select(Tenant)
            .where(*conditions)
            .options(selectinload(Tenant.property_ref))
            .order_by(Tenant.name)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await session.execute(query)
        tenants = result.scalars().all()

        # Get properties for filter dropdown
        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

    pagination_params = {
        "tenant_search": tenant_search,
        "property_id": selected_property_id or "",
        "active_only": str(active_only).lower(),
    }
    pagination_base = f"/tenants?{urlencode(pagination_params)}&"

    return templates.TemplateResponse(
        "tenants/list.html",
        {
            "request": request,
            "user": user,
            "tenants": tenants,
            "properties": properties,
            "property_id": selected_property_id,
            "active_only": active_only,
            "tenant_search": tenant_search,
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "pagination_base": pagination_base,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_tenant_form(request: Request, property_id: int = None):
    """Show new tenant form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get properties for dropdown
        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

        # Get PHAs for dropdown
        result = await session.execute(
            select(PHA).order_by(PHA.name)
        )
        phas = result.scalars().all()

    return templates.TemplateResponse(
        "tenants/form.html",
        {
            "request": request,
            "user": user,
            "tenant": None,
            "properties": properties,
            "phas": phas,
            "selected_property_id": property_id,
            "error": None,
        }
    )


@router.post("/new", response_class=HTMLResponse)
async def create_tenant(
    request: Request,
    property_id: int = Form(...),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    is_primary: str = Form(""),
    move_in_date: str = Form(""),
    notes: str = Form(""),
    is_section8: str = Form(""),
    pha_id: str = Form(""),
    voucher_amount: str = Form(""),
    tenant_portion: str = Form(""),
    current_rent: str = Form(""),
    lease_start_date: str = Form(""),
    lease_end_date: str = Form("")
):
    """Create a new tenant"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Convert checkbox strings to booleans
    is_primary_bool = is_primary.lower() == "true" if is_primary else False
    is_section8_bool = is_section8.lower() == "true" if is_section8 else False

    async with get_session() as session:
        # Verify property exists
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # If marking as primary, unmark any existing primary
        if is_primary_bool:
            result = await session.execute(
                select(Tenant).where(
                    Tenant.property_id == property_id,
                    Tenant.is_primary == True
                )
            )
            existing_primary = result.scalars().all()
            for t in existing_primary:
                t.is_primary = False

        # Parse dates
        move_in = None
        if move_in_date:
            try:
                move_in = date.fromisoformat(move_in_date)
            except ValueError:
                pass

        lease_start = None
        if lease_start_date:
            try:
                lease_start = date.fromisoformat(lease_start_date)
            except ValueError:
                pass

        lease_end = None
        if lease_end_date:
            try:
                lease_end = date.fromisoformat(lease_end_date)
            except ValueError:
                pass

        # Parse optional numeric fields
        parsed_pha_id = int(pha_id) if pha_id and pha_id.strip() else None
        parsed_voucher = Decimal(voucher_amount) if voucher_amount and voucher_amount.strip() else None
        parsed_tenant_portion = Decimal(tenant_portion) if tenant_portion and tenant_portion.strip() else None
        parsed_current_rent = Decimal(current_rent) if current_rent and current_rent.strip() else None

        # Create tenant
        tenant = Tenant(
            property_id=property_id,
            name=name,
            phone=phone or None,
            email=email.lower() if email else None,
            is_primary=is_primary_bool,
            is_active=True,
            move_in_date=move_in,
            lease_start_date=lease_start,
            lease_end_date=lease_end,
            notes=notes or None,
            is_section8=is_section8_bool,
            pha_id=parsed_pha_id if is_section8_bool else None,
            voucher_amount=parsed_voucher if is_section8_bool else None,
            tenant_portion=parsed_tenant_portion if is_section8_bool else None,
            current_rent=parsed_current_rent if not is_section8_bool else None
        )
        session.add(tenant)
        await session.commit()

        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)


@router.get("/{tenant_id}", response_class=HTMLResponse)
async def tenant_detail(request: Request, tenant_id: int):
    """Tenant detail page with payment history and property info"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Tenant + property
        result = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .options(
                selectinload(Tenant.property_ref),
                selectinload(Tenant.pha),
                selectinload(Tenant.autopay),
            )
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return RedirectResponse(url="/tenants", status_code=303)

        # ACH payments
        ach_result = await session.execute(
            select(RentPayment)
            .where(RentPayment.tenant_id == tenant_id)
            .options(selectinload(RentPayment.property_ref))
            .order_by(desc(RentPayment.initiated_at))
        )
        ach_payments = ach_result.scalars().all()

        # Stripe payments
        stripe_result = await session.execute(
            select(StripePayment)
            .where(StripePayment.tenant_id == tenant_id)
            .order_by(desc(StripePayment.initiated_at))
        )
        stripe_payments = stripe_result.scalars().all()

        # Imported payment history
        external_result = await session.execute(
            select(ExternalPayment)
            .where(ExternalPayment.tenant_id == tenant_id)
            .order_by(desc(ExternalPayment.paid_on))
        )
        external_payments = external_result.scalars().all()

        # Merge payments
        all_payments = []
        for p in ach_payments:
            all_payments.append({
                "method": "ach",
                "description": f"Rent - {p.payment_month.strftime('%b %Y')}" if p.payment_month else "Rent",
                "total_amount": float(p.total_amount or 0),
                "late_fee": float(p.late_fee or 0),
                "convenience_fee": 0,
                "status": p.status,
                "initiated_at": p.initiated_at,
                "is_autopay": p.is_autopay,
                "provider": "plaid",
                "external_id": p.plaid_transfer_id,
            })
        for p in stripe_payments:
            all_payments.append({
                "method": "card",
                "description": p.description,
                "total_amount": float(p.total_amount or 0),
                "late_fee": float(p.late_fee or 0),
                "convenience_fee": float(p.convenience_fee or 0),
                "status": p.status,
                "initiated_at": p.initiated_at,
                "is_autopay": False,
                "provider": "stripe",
                "external_id": p.stripe_checkout_session_id,
            })
        for p in external_payments:
            all_payments.append({
                "method": p.payment_method or "other",
                "description": p.description or f"{p.external_provider.title()} payment",
                "total_amount": float(p.amount or 0),
                "late_fee": 0,
                "convenience_fee": 0,
                "status": PaymentStatus(p.status),
                "initiated_at": datetime.combine(p.paid_on, datetime.min.time()),
                "is_autopay": False,
                "provider": p.external_provider,
                "external_id": p.external_id,
            })
        all_payments.sort(key=lambda x: x["initiated_at"] or datetime.min, reverse=True)

        # Payment stats
        total_paid = sum(p["total_amount"] for p in all_payments if p["status"] == PaymentStatus.COMPLETED)
        pending_amount = sum(p["total_amount"] for p in all_payments if p["status"] in (PaymentStatus.PENDING, PaymentStatus.PROCESSING))

        # Work orders
        wo_result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.tenant_id == tenant_id)
            .options(selectinload(WorkOrder.property_ref))
            .order_by(desc(WorkOrder.created_at))
        )
        work_orders = wo_result.scalars().all()
        open_wo_count = sum(1 for wo in work_orders if wo.status in (
            WorkOrderStatus.NEW, WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS
        ))

        # Active lease — prefer lease assigned to this tenant, fall back to property match
        lease_result = await session.execute(
            select(LeaseDocument)
            .where(
                LeaseDocument.tenant_id == tenant_id,
                LeaseDocument.status != LeaseStatus.TERMINATED,
            )
            .order_by(desc(LeaseDocument.created_at))
            .limit(1)
        )
        active_lease = lease_result.scalar_one_or_none()
        if not active_lease and tenant.property_id:
            lease_result = await session.execute(
                select(LeaseDocument)
                .where(
                    LeaseDocument.property_id == tenant.property_id,
                    LeaseDocument.status != LeaseStatus.TERMINATED,
                )
                .order_by(desc(LeaseDocument.created_at))
                .limit(1)
            )
            active_lease = lease_result.scalar_one_or_none()

        # Water bills (ordered by scrape time — statement_date may be null)
        bill_result = await session.execute(
            select(WaterBill)
            .where(WaterBill.property_id == tenant.property_id)
            .order_by(desc(WaterBill.scraped_at))
            .limit(6)
        )
        water_bills = bill_result.scalars().all()

        # Bank accounts
        bank_result = await session.execute(
            select(TenantBankAccount)
            .where(TenantBankAccount.tenant_id == tenant_id)
            .order_by(desc(TenantBankAccount.linked_at))
        )
        bank_accounts = bank_result.scalars().all()

    # Water bill balance = latest bill amount only (each bill is a scrape snapshot, not a separate charge)
    water_balance = float(water_bills[0].amount_due or 0) if water_bills and water_bills[0].amount_due else 0.0
    ledger_charges = await ledger_service.list_charges(tenant_id=tenant_id, include_paid=True)
    ledger_totals = ledger_service.totals(ledger_charges)

    # Financial overview — make lease economics and rent collection the primary story.
    if tenant.is_section8:
        monthly_rent_total = Decimal(tenant.voucher_amount or 0) + Decimal(tenant.tenant_portion or 0)
    elif tenant.current_rent is not None:
        monthly_rent_total = Decimal(tenant.current_rent)
    elif active_lease and active_lease.monthly_rent is not None:
        monthly_rent_total = Decimal(active_lease.monthly_rent)
    else:
        monthly_rent_total = Decimal("0.00")

    lease_start = tenant.lease_start_date or (active_lease.lease_start if active_lease else None)
    lease_end = tenant.lease_end_date or (active_lease.lease_end if active_lease else None)
    lease_months = None
    lease_contract_total = None
    if lease_start and lease_end and lease_end >= lease_start:
        lease_months = ((lease_end.year - lease_start.year) * 12) + lease_end.month - lease_start.month + 1
        lease_contract_total = monthly_rent_total * lease_months

    rent_received = Decimal("0.00")
    ledger_payment_activity = []
    ledger_provider_keys = set()
    for charge in ledger_charges:
        for entry in charge["entries"]:
            amount = ledger_service.money(entry.amount)
            if charge["charge_type"] == "rent" and charge["status"] != "void":
                if entry.status == "posted" and entry.entry_type == "payment":
                    rent_received += amount
                elif entry.status == "posted" and entry.entry_type == "reversal":
                    rent_received -= amount

            if entry.entry_type != "payment":
                continue
            # These entries allocate imported charge balances. The source
            # deposits are rendered separately as the actual transactions.
            if entry.external_provider == "turbotenant_charge":
                continue
            if entry.external_provider and entry.external_id:
                ledger_provider_keys.add((entry.external_provider, entry.external_id))
            ledger_payment_activity.append({
                "method": entry.payment_method or "manual",
                "description": entry.description or charge["description"],
                "total_amount": float(amount),
                "convenience_fee": 0,
                "status": "completed" if entry.status == "posted" else entry.status,
                "initiated_at": entry.created_at,
                "is_autopay": False,
            })
    rent_received = max(rent_received, Decimal("0.00"))
    if rent_received == 0 and total_paid > 0:
        # Legacy provider payments predate the shared ledger, so retain them as a fallback.
        rent_received = ledger_service.money(total_paid)

    payment_activity = ledger_payment_activity + [
        {
            **payment,
            "status": payment["status"].value if payment["status"] else "pending",
        }
        for payment in all_payments
        if not payment["external_id"]
        or (payment["provider"], payment["external_id"]) not in ledger_provider_keys
    ]
    payment_activity.sort(key=lambda item: item["initiated_at"] or datetime.min, reverse=True)

    open_charge_count = sum(
        1 for charge in ledger_charges if charge["status"] in {"open", "partial", "overdue"}
    )

    return templates.TemplateResponse(
        "tenants/detail.html",
        {
            "request": request,
            "user": user,
            "tenant": tenant,
            "payments": payment_activity,
            "total_paid": total_paid,
            "pending_amount": pending_amount,
            "work_orders": work_orders,
            "open_wo_count": open_wo_count,
            "active_lease": active_lease,
            "water_bills": water_bills,
            "bank_accounts": bank_accounts,
            "water_balance": water_balance,
            "ledger_totals": ledger_totals,
            "monthly_rent_total": monthly_rent_total,
            "rent_received": rent_received,
            "lease_start": lease_start,
            "lease_end": lease_end,
            "lease_months": lease_months,
            "lease_contract_total": lease_contract_total,
            "open_charge_count": open_charge_count,
        }
    )


@router.get("/{tenant_id}/edit", response_class=HTMLResponse)
async def edit_tenant_form(request: Request, tenant_id: int):
    """Show edit tenant form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .options(selectinload(Tenant.pha))
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Get properties for dropdown
        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

        # Get PHAs for dropdown
        result = await session.execute(
            select(PHA).order_by(PHA.name)
        )
        phas = result.scalars().all()

    return templates.TemplateResponse(
        "tenants/form.html",
        {
            "request": request,
            "user": user,
            "tenant": tenant,
            "properties": properties,
            "phas": phas,
            "selected_property_id": tenant.property_id,
            "error": None,
        }
    )


@router.post("/{tenant_id}/edit", response_class=HTMLResponse)
async def update_tenant(
    request: Request,
    tenant_id: int,
    property_id: int = Form(...),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    is_primary: str = Form(""),
    is_active: str = Form(""),
    move_in_date: str = Form(""),
    move_out_date: str = Form(""),
    notes: str = Form(""),
    is_section8: str = Form(""),
    pha_id: str = Form(""),
    voucher_amount: str = Form(""),
    tenant_portion: str = Form(""),
    current_rent: str = Form(""),
    lease_start_date: str = Form(""),
    lease_end_date: str = Form("")
):
    """Update a tenant"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Convert checkbox strings to booleans
    is_primary_bool = is_primary.lower() == "true" if is_primary else False
    is_active_bool = is_active.lower() == "true" if is_active else False
    is_section8_bool = is_section8.lower() == "true" if is_section8 else False

    async with get_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # If marking as primary, unmark any existing primary
        if is_primary_bool and not tenant.is_primary:
            result = await session.execute(
                select(Tenant).where(
                    Tenant.property_id == property_id,
                    Tenant.is_primary == True,
                    Tenant.id != tenant_id
                )
            )
            existing_primary = result.scalars().all()
            for t in existing_primary:
                t.is_primary = False

        # Parse dates
        move_in = None
        if move_in_date:
            try:
                move_in = date.fromisoformat(move_in_date)
            except ValueError:
                pass

        move_out = None
        if move_out_date:
            try:
                move_out = date.fromisoformat(move_out_date)
            except ValueError:
                pass

        lease_start = None
        if lease_start_date:
            try:
                lease_start = date.fromisoformat(lease_start_date)
            except ValueError:
                pass

        lease_end = None
        if lease_end_date:
            try:
                lease_end = date.fromisoformat(lease_end_date)
            except ValueError:
                pass

        # Parse optional numeric fields
        parsed_pha_id = int(pha_id) if pha_id and pha_id.strip() else None
        parsed_voucher = Decimal(voucher_amount) if voucher_amount and voucher_amount.strip() else None
        parsed_tenant_portion = Decimal(tenant_portion) if tenant_portion and tenant_portion.strip() else None
        parsed_current_rent = Decimal(current_rent) if current_rent and current_rent.strip() else None

        # Update tenant
        tenant.property_id = property_id
        tenant.name = name
        tenant.phone = phone or None
        tenant.email = email.lower() if email else None
        tenant.is_primary = is_primary_bool
        tenant.is_active = is_active_bool
        tenant.move_in_date = move_in
        tenant.move_out_date = move_out
        tenant.lease_start_date = lease_start
        tenant.lease_end_date = lease_end
        tenant.notes = notes or None
        tenant.is_section8 = is_section8_bool
        tenant.pha_id = parsed_pha_id if is_section8_bool else None
        tenant.voucher_amount = parsed_voucher if is_section8_bool else None
        tenant.tenant_portion = parsed_tenant_portion if is_section8_bool else None
        tenant.current_rent = parsed_current_rent if not is_section8_bool else None

        await session.commit()

        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)


@router.post("/{tenant_id}/archive")
async def archive_tenant(request: Request, tenant_id: int):
    """Archive (deactivate) a tenant"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        property_id = tenant.property_id
        tenant.is_active = False
        tenant.move_out_date = tenant.move_out_date or date.today()
        await session.commit()

    return RedirectResponse(url=f"/tenants/{tenant_id}", status_code=303)


@router.post("/{tenant_id}/restore")
async def restore_tenant(request: Request, tenant_id: int):
    """Restore an archived tenant"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        tenant.is_active = True
        tenant.move_out_date = None
        await session.commit()

    return RedirectResponse(url=f"/tenants/{tenant_id}", status_code=303)
