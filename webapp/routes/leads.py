"""Lead management routes — Section 8 tenant lead tracker"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Lead, LeadStatus, Property, PHA, Tenant
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["leads"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_leads(
    request: Request,
    status: str = None,
    property_id: int = None,
):
    """List all leads with optional status/property filters"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Status counts for filter pills
        count_query = select(
            Lead.status, func.count(Lead.id)
        ).group_by(Lead.status)
        count_result = await session.execute(count_query)
        status_counts = dict(count_result.all())
        total_count = sum(status_counts.values())

        # Filtered query
        query = select(Lead).options(
            selectinload(Lead.property_ref),
            selectinload(Lead.pha),
        )

        if status:
            query = query.where(Lead.status == status)
        if property_id:
            query = query.where(Lead.property_id == property_id)

        query = query.order_by(Lead.created_at.desc())
        result = await session.execute(query)
        leads = result.scalars().all()

        # Properties for filter dropdown
        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

    return templates.TemplateResponse(
        "leads/list.html",
        {
            "request": request,
            "user": user,
            "leads": leads,
            "properties": properties,
            "status_filter": status,
            "property_id": property_id,
            "status_counts": status_counts,
            "total_count": total_count,
            "LeadStatus": LeadStatus,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_lead_form(request: Request):
    """Show create lead form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

        result = await session.execute(select(PHA).order_by(PHA.name))
        phas = result.scalars().all()

    return templates.TemplateResponse(
        "leads/form.html",
        {
            "request": request,
            "user": user,
            "lead": None,
            "properties": properties,
            "phas": phas,
            "error": None,
            "LeadStatus": LeadStatus,
        }
    )


@router.post("/new", response_class=HTMLResponse)
async def create_lead(
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    has_section8_voucher: str = Form(""),
    pha_id: str = Form(""),
    voucher_amount: str = Form(""),
    current_pha_name: str = Form(""),
    property_id: str = Form(""),
    desired_bedrooms: str = Form(""),
    desired_move_in: str = Form(""),
    source: str = Form(""),
    notes: str = Form(""),
):
    """Create a new lead"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    has_voucher = has_section8_voucher.lower() == "true" if has_section8_voucher else False
    parsed_pha_id = int(pha_id) if pha_id and pha_id.strip() else None
    parsed_voucher = Decimal(voucher_amount) if voucher_amount and voucher_amount.strip() else None
    parsed_property_id = int(property_id) if property_id and property_id.strip() else None
    parsed_bedrooms = int(desired_bedrooms) if desired_bedrooms and desired_bedrooms.strip() else None

    parsed_move_in = None
    if desired_move_in:
        try:
            parsed_move_in = date.fromisoformat(desired_move_in)
        except ValueError:
            pass

    async with get_session() as session:
        lead = Lead(
            name=name,
            phone=phone or None,
            email=email.lower() if email else None,
            has_section8_voucher=has_voucher,
            pha_id=parsed_pha_id if has_voucher else None,
            voucher_amount=parsed_voucher if has_voucher else None,
            current_pha_name=current_pha_name or None,
            property_id=parsed_property_id,
            desired_bedrooms=parsed_bedrooms,
            desired_move_in=parsed_move_in,
            status=LeadStatus.NEW.value,
            source=source or None,
            notes=notes or None,
        )
        session.add(lead)
        await session.commit()

        return RedirectResponse(url="/leads", status_code=303)


@router.get("/{lead_id}", response_class=HTMLResponse)
async def lead_detail(request: Request, lead_id: int):
    """Lead detail page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Lead).options(
                selectinload(Lead.property_ref),
                selectinload(Lead.pha),
                selectinload(Lead.converted_tenant),
            ).where(Lead.id == lead_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            return RedirectResponse(url="/leads", status_code=303)

    return templates.TemplateResponse(
        "leads/detail.html",
        {
            "request": request,
            "user": user,
            "lead": lead,
            "LeadStatus": LeadStatus,
            "error": request.query_params.get("error"),
        }
    )


@router.get("/{lead_id}/edit", response_class=HTMLResponse)
async def edit_lead_form(request: Request, lead_id: int):
    """Show edit lead form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Lead).options(
                selectinload(Lead.property_ref),
                selectinload(Lead.pha),
            ).where(Lead.id == lead_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            return RedirectResponse(url="/leads", status_code=303)

        result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = result.scalars().all()

        result = await session.execute(select(PHA).order_by(PHA.name))
        phas = result.scalars().all()

    return templates.TemplateResponse(
        "leads/form.html",
        {
            "request": request,
            "user": user,
            "lead": lead,
            "properties": properties,
            "phas": phas,
            "error": None,
            "LeadStatus": LeadStatus,
        }
    )


@router.post("/{lead_id}/edit", response_class=HTMLResponse)
async def update_lead(
    request: Request,
    lead_id: int,
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    has_section8_voucher: str = Form(""),
    pha_id: str = Form(""),
    voucher_amount: str = Form(""),
    current_pha_name: str = Form(""),
    property_id: str = Form(""),
    desired_bedrooms: str = Form(""),
    desired_move_in: str = Form(""),
    status: str = Form(""),
    source: str = Form(""),
    notes: str = Form(""),
):
    """Update an existing lead"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    has_voucher = has_section8_voucher.lower() == "true" if has_section8_voucher else False
    parsed_pha_id = int(pha_id) if pha_id and pha_id.strip() else None
    parsed_voucher = Decimal(voucher_amount) if voucher_amount and voucher_amount.strip() else None
    parsed_property_id = int(property_id) if property_id and property_id.strip() else None
    parsed_bedrooms = int(desired_bedrooms) if desired_bedrooms and desired_bedrooms.strip() else None

    parsed_move_in = None
    if desired_move_in:
        try:
            parsed_move_in = date.fromisoformat(desired_move_in)
        except ValueError:
            pass

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            return RedirectResponse(url="/leads", status_code=303)

        lead.name = name
        lead.phone = phone or None
        lead.email = email.lower() if email else None
        lead.has_section8_voucher = has_voucher
        lead.pha_id = parsed_pha_id if has_voucher else None
        lead.voucher_amount = parsed_voucher if has_voucher else None
        lead.current_pha_name = current_pha_name or None
        lead.property_id = parsed_property_id
        lead.desired_bedrooms = parsed_bedrooms
        lead.desired_move_in = parsed_move_in
        lead.status = status if status else lead.status
        lead.source = source or None
        lead.notes = notes or None

        await session.commit()

        return RedirectResponse(url=f"/leads/{lead_id}", status_code=303)


@router.post("/{lead_id}/convert", response_class=HTMLResponse)
async def convert_lead(request: Request, lead_id: int):
    """Convert a lead into a Tenant record"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if not lead:
            return RedirectResponse(url="/leads", status_code=303)

        # Already converted
        if lead.status == LeadStatus.CONVERTED.value and lead.converted_tenant_id:
            return RedirectResponse(url=f"/tenants/{lead.converted_tenant_id}", status_code=303)

        # Must have property assigned
        if not lead.property_id:
            return RedirectResponse(
                url=f"/leads/{lead_id}?error=Property+must+be+assigned+before+converting",
                status_code=303,
            )

        # Create Tenant pre-filled from lead data
        tenant = Tenant(
            property_id=lead.property_id,
            name=lead.name,
            phone=lead.phone,
            email=lead.email,
            is_active=True,
            is_section8=lead.has_section8_voucher,
            pha_id=lead.pha_id if lead.has_section8_voucher else None,
            voucher_amount=lead.voucher_amount if lead.has_section8_voucher else None,
            move_in_date=lead.desired_move_in,
        )
        session.add(tenant)
        await session.flush()  # get tenant.id

        lead.status = LeadStatus.CONVERTED.value
        lead.converted_tenant_id = tenant.id
        await session.commit()

        return RedirectResponse(url=f"/tenants/{tenant.id}", status_code=303)


@router.post("/{lead_id}/delete", response_class=HTMLResponse)
async def delete_lead(request: Request, lead_id: int):
    """Delete a lead"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(select(Lead).where(Lead.id == lead_id))
        lead = result.scalar_one_or_none()
        if lead:
            await session.delete(lead)
            await session.commit()

    return RedirectResponse(url="/leads", status_code=303)
