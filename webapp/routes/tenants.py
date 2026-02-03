"""Tenant management routes"""

from datetime import date
from pathlib import Path

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
    is_primary: bool = Form(False),
    move_in_date: str = Form(""),
    notes: str = Form(""),
    is_section8: bool = Form(False),
    pha_id: int = Form(None),
    voucher_amount: float = Form(None),
    tenant_portion: float = Form(None)
):
    """Create a new tenant"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Verify property exists
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # If marking as primary, unmark any existing primary
        if is_primary:
            result = await session.execute(
                select(Tenant).where(
                    Tenant.property_id == property_id,
                    Tenant.is_primary == True
                )
            )
            existing_primary = result.scalars().all()
            for t in existing_primary:
                t.is_primary = False

        # Parse move-in date
        move_in = None
        if move_in_date:
            try:
                move_in = date.fromisoformat(move_in_date)
            except ValueError:
                pass

        # Create tenant
        tenant = Tenant(
            property_id=property_id,
            name=name,
            phone=phone or None,
            email=email.lower() if email else None,
            is_primary=is_primary,
            is_active=True,
            move_in_date=move_in,
            notes=notes or None,
            is_section8=is_section8,
            pha_id=pha_id if is_section8 and pha_id else None,
            voucher_amount=Decimal(str(voucher_amount)) if is_section8 and voucher_amount else None,
            tenant_portion=Decimal(str(tenant_portion)) if is_section8 and tenant_portion else None
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
    is_primary: bool = Form(False),
    is_active: bool = Form(True),
    move_in_date: str = Form(""),
    move_out_date: str = Form(""),
    notes: str = Form(""),
    is_section8: bool = Form(False),
    pha_id: int = Form(None),
    voucher_amount: float = Form(None),
    tenant_portion: float = Form(None)
):
    """Update a tenant"""
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

        # If marking as primary, unmark any existing primary
        if is_primary and not tenant.is_primary:
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

        # Update tenant
        tenant.property_id = property_id
        tenant.name = name
        tenant.phone = phone or None
        tenant.email = email.lower() if email else None
        tenant.is_primary = is_primary
        tenant.is_active = is_active
        tenant.move_in_date = move_in
        tenant.move_out_date = move_out
        tenant.notes = notes or None
        tenant.is_section8 = is_section8
        tenant.pha_id = pha_id if is_section8 and pha_id else None
        tenant.voucher_amount = Decimal(str(voucher_amount)) if is_section8 and voucher_amount else None
        tenant.tenant_portion = Decimal(str(tenant_portion)) if is_section8 and tenant_portion else None

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
