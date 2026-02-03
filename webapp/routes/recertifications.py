"""Recertification management routes"""

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Recertification, RecertStatus, Tenant, Property, PHA
from webapp.auth.dependencies import get_current_user
from webapp.services.email_service import email_service
from webapp.config import web_config

router = APIRouter(tags=["recertifications"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Email template for recertification request
RECERT_EMAIL_TEMPLATE = """Dear {pha_contact},

I am writing to request a rent increase recertification for the following tenant and property:

PROPERTY INFORMATION:
Address: {property_address}

TENANT INFORMATION:
Tenant Name: {tenant_name}
Lease Start Date: {lease_start_date}

RENT INFORMATION:
Current Rent: ${current_rent}
Proposed New Rent: ${proposed_rent}
Proposed Increase: ${rent_increase} ({increase_percent:.1f}%)

The tenant has been in the unit for 9 months as of {eligible_date}, making them eligible for a rent recertification under the Housing Choice Voucher Program guidelines.

Please let me know if you need any additional documentation to process this request.

Thank you for your assistance.

Best regards,
{sender_name}
"""


@router.get("/", response_class=HTMLResponse)
async def list_recertifications(request: Request, status: str = None):
    """List all recertifications"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(Recertification)
            .options(
                selectinload(Recertification.tenant),
                selectinload(Recertification.property_ref),
                selectinload(Recertification.pha)
            )
        )

        if status:
            try:
                status_enum = RecertStatus(status)
                query = query.where(Recertification.status == status_enum)
            except ValueError:
                pass

        result = await session.execute(
            query.order_by(Recertification.eligible_date.asc())
        )
        recertifications = result.scalars().all()

        # Count by status
        status_counts = {}
        total_count = 0
        for s in RecertStatus:
            count_result = await session.execute(
                select(Recertification).where(Recertification.status == s)
            )
            count = len(count_result.scalars().all())
            status_counts[s.value] = count
            total_count += count

    return templates.TemplateResponse(
        "recertifications/list.html",
        {
            "request": request,
            "user": user,
            "recertifications": recertifications,
            "status_filter": status,
            "status_counts": status_counts,
            "total_count": total_count,
            "RecertStatus": RecertStatus,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_recert_form(request: Request, tenant_id: int = None):
    """Show new recertification form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get active tenants with lease info
        result = await session.execute(
            select(Tenant)
            .where(Tenant.is_active == True)
            .options(selectinload(Tenant.property_ref))
            .order_by(Tenant.name)
        )
        tenants = result.scalars().all()

        # Get PHAs
        result = await session.execute(
            select(PHA).order_by(PHA.name)
        )
        phas = result.scalars().all()

        selected_tenant = None
        if tenant_id:
            for t in tenants:
                if t.id == tenant_id:
                    selected_tenant = t
                    break

    return templates.TemplateResponse(
        "recertifications/form.html",
        {
            "request": request,
            "user": user,
            "recertification": None,
            "tenants": tenants,
            "phas": phas,
            "selected_tenant": selected_tenant,
            "error": None,
        }
    )


@router.post("/new", response_class=HTMLResponse)
async def create_recertification(
    request: Request,
    tenant_id: int = Form(...),
    pha_id: int = Form(None),
    current_rent: float = Form(...),
    proposed_rent: float = Form(...),
    lease_start_date: str = Form(...),
    notes: str = Form("")
):
    """Create a new recertification"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Parse lease start date
    try:
        lease_start = date.fromisoformat(lease_start_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lease start date")

    # Calculate eligible date (9 months after lease start)
    eligible_date = lease_start + relativedelta(months=9)

    # Determine initial status
    today = date.today()
    if today >= eligible_date:
        initial_status = RecertStatus.ELIGIBLE
    else:
        initial_status = RecertStatus.PENDING

    async with get_session() as session:
        # Get tenant to get property_id
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        # Update tenant's lease info
        tenant.lease_start_date = lease_start
        tenant.current_rent = current_rent
        tenant.proposed_rent = proposed_rent

        recert = Recertification(
            tenant_id=tenant_id,
            property_id=tenant.property_id,
            pha_id=pha_id if pha_id else None,
            current_rent=current_rent,
            proposed_rent=proposed_rent,
            lease_start_date=lease_start,
            eligible_date=eligible_date,
            status=initial_status,
            notes=notes or None
        )
        session.add(recert)
        await session.commit()

        return RedirectResponse(url="/recertifications", status_code=303)


@router.get("/{recert_id}", response_class=HTMLResponse)
async def recert_detail(request: Request, recert_id: int):
    """Show recertification detail page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Recertification)
            .where(Recertification.id == recert_id)
            .options(
                selectinload(Recertification.tenant),
                selectinload(Recertification.property_ref),
                selectinload(Recertification.pha)
            )
        )
        recert = result.scalar_one_or_none()

        if not recert:
            raise HTTPException(status_code=404, detail="Recertification not found")

        # Get all PHAs for selection
        result = await session.execute(
            select(PHA).order_by(PHA.name)
        )
        phas = result.scalars().all()

    return templates.TemplateResponse(
        "recertifications/detail.html",
        {
            "request": request,
            "user": user,
            "recert": recert,
            "phas": phas,
            "has_email": web_config.has_sendgrid or web_config.has_smtp,
        }
    )


@router.post("/{recert_id}/update-status")
async def update_recert_status(
    request: Request,
    recert_id: int,
    status: str = Form(...),
    approved_rent: float = Form(None),
    effective_date: str = Form(""),
    pha_response: str = Form("")
):
    """Update recertification status"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        new_status = RecertStatus(status)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid status")

    async with get_session() as session:
        result = await session.execute(
            select(Recertification).where(Recertification.id == recert_id)
        )
        recert = result.scalar_one_or_none()

        if not recert:
            raise HTTPException(status_code=404, detail="Recertification not found")

        recert.status = new_status

        if approved_rent:
            recert.approved_rent = approved_rent

        if effective_date:
            try:
                recert.effective_date = date.fromisoformat(effective_date)
            except ValueError:
                pass

        if pha_response:
            recert.pha_response = pha_response

        await session.commit()

    return RedirectResponse(url=f"/recertifications/{recert_id}", status_code=303)


@router.post("/{recert_id}/send-email")
async def send_recert_email(
    request: Request,
    recert_id: int,
    pha_id: int = Form(None),
    custom_message: str = Form("")
):
    """Send recertification request email to PHA"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Recertification)
            .where(Recertification.id == recert_id)
            .options(
                selectinload(Recertification.tenant),
                selectinload(Recertification.property_ref),
                selectinload(Recertification.pha)
            )
        )
        recert = result.scalar_one_or_none()

        if not recert:
            raise HTTPException(status_code=404, detail="Recertification not found")

        # Update PHA if provided
        if pha_id and pha_id != recert.pha_id:
            recert.pha_id = pha_id
            await session.flush()
            # Reload to get PHA
            await session.refresh(recert)
            result = await session.execute(
                select(PHA).where(PHA.id == pha_id)
            )
            pha = result.scalar_one_or_none()
        else:
            pha = recert.pha

        if not pha or not pha.email:
            raise HTTPException(status_code=400, detail="PHA email not configured")

        # Format email
        rent_increase = float(recert.proposed_rent - recert.current_rent)
        increase_percent = (rent_increase / float(recert.current_rent)) * 100 if recert.current_rent else 0

        if custom_message:
            email_body = custom_message
        else:
            email_body = RECERT_EMAIL_TEMPLATE.format(
                pha_contact=pha.contact_name or "Housing Authority",
                property_address=recert.property_ref.address,
                tenant_name=recert.tenant.name,
                lease_start_date=recert.lease_start_date.strftime('%B %d, %Y') if recert.lease_start_date else 'N/A',
                current_rent=f"{recert.current_rent:.2f}",
                proposed_rent=f"{recert.proposed_rent:.2f}",
                rent_increase=f"{rent_increase:.2f}",
                increase_percent=increase_percent,
                eligible_date=recert.eligible_date.strftime('%B %d, %Y') if recert.eligible_date else 'N/A',
                sender_name=user.get('name') or user.get('email')
            )

        # Send email
        result = await email_service.send_email(
            to=pha.email,
            subject=f"Rent Increase Recertification Request - {recert.property_ref.address}",
            body=email_body
        )

        if result.success:
            recert.status = RecertStatus.SUBMITTED
            recert.submitted_date = date.today()
            recert.last_email_sent = datetime.utcnow()
            recert.email_count = (recert.email_count or 0) + 1
            await session.commit()
        else:
            raise HTTPException(status_code=500, detail=f"Failed to send email: {result.error_message}")

    return RedirectResponse(url=f"/recertifications/{recert_id}", status_code=303)


@router.post("/{recert_id}/delete")
async def delete_recertification(request: Request, recert_id: int):
    """Delete a recertification"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Recertification).where(Recertification.id == recert_id)
        )
        recert = result.scalar_one_or_none()

        if not recert:
            raise HTTPException(status_code=404, detail="Recertification not found")

        await session.delete(recert)
        await session.commit()

    return RedirectResponse(url="/recertifications", status_code=303)
