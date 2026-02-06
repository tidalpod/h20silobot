"""Tenant management routes"""

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Tenant, Property, PHA
from webapp.auth.dependencies import get_current_user
from decimal import Decimal

router = APIRouter(tags=["tenants"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_tenants(
    request: Request,
    property_id: int = None,
    active_only: bool = True
):
    """List all tenants"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = select(Tenant).options(selectinload(Tenant.property_ref))

        if property_id:
            query = query.where(Tenant.property_id == property_id)

        if active_only:
            query = query.where(Tenant.is_active == True)

        result = await session.execute(query.order_by(Tenant.name))
        tenants = result.scalars().all()

        # Get properties for filter dropdown
        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

    return templates.TemplateResponse(
        "tenants/list.html",
        {
            "request": request,
            "user": user,
            "tenants": tenants,
            "properties": properties,
            "property_id": property_id,
            "active_only": active_only,
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


@router.post("/{tenant_id}/delete")
async def delete_tenant(request: Request, tenant_id: int):
    """Delete (deactivate) a tenant"""
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
        tenant.move_out_date = date.today()
        await session.commit()

    return RedirectResponse(url=f"/properties/{property_id}", status_code=303)
