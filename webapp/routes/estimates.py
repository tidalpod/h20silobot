"""PM-side Estimate management routes"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Estimate, EstimateStatus, Invoice, InvoiceStatus,
    Vendor, Property, Project,
)
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["estimates"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def estimate_list(request: Request):
    """List all estimates with filters"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    status_filter = request.query_params.get("status", "")
    vendor_filter = request.query_params.get("vendor_id", "")
    property_filter = request.query_params.get("property_id", "")

    async with get_session() as session:
        query = (
            select(Estimate)
            .options(
                selectinload(Estimate.vendor_ref),
                selectinload(Estimate.property_ref),
                selectinload(Estimate.project_ref),
            )
        )

        if status_filter:
            query = query.where(Estimate.status == status_filter)
        if vendor_filter:
            query = query.where(Estimate.vendor_id == int(vendor_filter))
        if property_filter:
            query = query.where(Estimate.property_id == int(property_filter))

        query = query.order_by(desc(Estimate.created_at))
        result = await session.execute(query)
        estimates = result.scalars().all()

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        total_result = await session.execute(select(func.sum(Estimate.amount)))
        total_amount = total_result.scalar() or 0

        pending_result = await session.execute(
            select(func.sum(Estimate.amount)).where(Estimate.status == EstimateStatus.SUBMITTED.value)
        )
        pending_amount = pending_result.scalar() or 0

    return templates.TemplateResponse("estimates/list.html", {
        "request": request,
        "user": user,
        "estimates": estimates,
        "vendors": vendors,
        "properties": properties,
        "status_filter": status_filter,
        "vendor_filter": vendor_filter,
        "property_filter": property_filter,
        "total_amount": total_amount,
        "pending_amount": pending_amount,
        "EstimateStatus": EstimateStatus,
    })


@router.get("/{estimate_id}", response_class=HTMLResponse)
async def estimate_detail(request: Request, estimate_id: int):
    """Estimate detail with approve/reject/convert actions"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Estimate)
            .where(Estimate.id == estimate_id)
            .options(
                selectinload(Estimate.vendor_ref),
                selectinload(Estimate.property_ref),
                selectinload(Estimate.project_ref),
                selectinload(Estimate.invoice_ref),
            )
        )
        estimate = result.scalar_one_or_none()
        if not estimate:
            return RedirectResponse(url="/estimates", status_code=303)

    return templates.TemplateResponse("estimates/detail.html", {
        "request": request,
        "user": user,
        "estimate": estimate,
    })


@router.post("/{estimate_id}/approve")
async def estimate_approve(request: Request, estimate_id: int):
    """Approve an estimate"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Estimate).where(Estimate.id == estimate_id)
        )
        estimate = result.scalar_one_or_none()
        if estimate:
            estimate.status = EstimateStatus.APPROVED.value
            estimate.approved_at = datetime.utcnow()
            if form.get("notes"):
                estimate.notes = form["notes"]

    redirect = form.get("redirect", f"/estimates/{estimate_id}")
    return RedirectResponse(url=redirect, status_code=303)


@router.post("/{estimate_id}/reject")
async def estimate_reject(request: Request, estimate_id: int):
    """Reject an estimate"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Estimate).where(Estimate.id == estimate_id)
        )
        estimate = result.scalar_one_or_none()
        if estimate:
            estimate.status = EstimateStatus.REJECTED.value
            estimate.rejected_at = datetime.utcnow()
            estimate.notes = form.get("notes", "")

    redirect = form.get("redirect", f"/estimates/{estimate_id}")
    return RedirectResponse(url=redirect, status_code=303)


@router.post("/{estimate_id}/convert")
async def estimate_convert_to_invoice(request: Request, estimate_id: int):
    """Convert an approved estimate to an invoice"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Estimate).where(Estimate.id == estimate_id)
        )
        estimate = result.scalar_one_or_none()
        if not estimate or estimate.status != EstimateStatus.APPROVED.value:
            return RedirectResponse(url=f"/estimates/{estimate_id}", status_code=303)

        if estimate.invoice_id:
            return RedirectResponse(url=f"/estimates/{estimate_id}", status_code=303)

        invoice = Invoice(
            vendor_id=estimate.vendor_id,
            property_id=estimate.property_id,
            project_id=estimate.project_id,
            title=f"From Estimate: {estimate.title}",
            description=estimate.description,
            amount=estimate.amount,
            file_url=estimate.file_url,
            status=InvoiceStatus.SUBMITTED.value,
            submitted_at=datetime.utcnow(),
        )
        session.add(invoice)
        await session.flush()

        estimate.invoice_id = invoice.id

    return RedirectResponse(url=f"/estimates/{estimate_id}", status_code=303)
