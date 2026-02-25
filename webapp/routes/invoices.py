"""PM-side Invoice management routes"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Invoice, InvoiceStatus, Vendor, Property, WorkOrder, Project,
)
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["invoices"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
INVOICE_UPLOAD_DIR = Path(UPLOAD_BASE) / "invoices"
INVOICE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/", response_class=HTMLResponse)
async def invoice_list(request: Request):
    """List all invoices with filters"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Filters
    status_filter = request.query_params.get("status", "")
    vendor_filter = request.query_params.get("vendor_id", "")
    property_filter = request.query_params.get("property_id", "")

    async with get_session() as session:
        query = (
            select(Invoice)
            .options(
                selectinload(Invoice.vendor_ref),
                selectinload(Invoice.property_ref),
                selectinload(Invoice.project_ref),
            )
        )

        if status_filter:
            query = query.where(Invoice.status == InvoiceStatus(status_filter))
        if vendor_filter:
            query = query.where(Invoice.vendor_id == int(vendor_filter))
        if property_filter:
            query = query.where(Invoice.property_id == int(property_filter))

        query = query.order_by(desc(Invoice.created_at))
        result = await session.execute(query)
        invoices = result.scalars().all()

        # Get vendors and properties for filter dropdowns
        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        # Summary stats
        total_result = await session.execute(select(func.sum(Invoice.amount)))
        total_amount = total_result.scalar() or 0

        pending_result = await session.execute(
            select(func.sum(Invoice.amount)).where(Invoice.status == InvoiceStatus.SUBMITTED)
        )
        pending_amount = pending_result.scalar() or 0

    return templates.TemplateResponse("invoices/list.html", {
        "request": request,
        "user": user,
        "invoices": invoices,
        "vendors": vendors,
        "properties": properties,
        "status_filter": status_filter,
        "vendor_filter": vendor_filter,
        "property_filter": property_filter,
        "total_amount": total_amount,
        "pending_amount": pending_amount,
        "InvoiceStatus": InvoiceStatus,
    })


@router.get("/new", response_class=HTMLResponse)
async def invoice_form(request: Request):
    """Manual invoice creation form (PM use)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        projects_result = await session.execute(
            select(Project).order_by(desc(Project.created_at))
        )
        projects = projects_result.scalars().all()

    return templates.TemplateResponse("invoices/form.html", {
        "request": request,
        "user": user,
        "vendors": vendors,
        "properties": properties,
        "projects": projects,
        "invoice": None,
    })


@router.post("/new")
async def invoice_create(request: Request):
    """Create invoice manually"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    file: UploadFile = form.get("file")

    file_url = None
    if file and file.filename:
        allowed_types = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        if file.content_type in allowed_types:
            contents = await file.read()
            if len(contents) <= 20 * 1024 * 1024:
                ext = allowed_types.get(file.content_type, ".pdf")
                filename = f"invoice_{uuid.uuid4().hex[:12]}{ext}"
                filepath = INVOICE_UPLOAD_DIR / filename
                with open(filepath, "wb") as f:
                    f.write(contents)
                file_url = f"/uploads/invoices/{filename}"

    async with get_session() as session:
        invoice = Invoice(
            vendor_id=int(form["vendor_id"]),
            property_id=int(form["property_id"]),
            work_order_id=int(form["work_order_id"]) if form.get("work_order_id") else None,
            project_id=int(form["project_id"]) if form.get("project_id") else None,
            title=form["title"],
            description=form.get("description", ""),
            amount=float(form["amount"]),
            file_url=file_url,
            status=InvoiceStatus(form.get("status", "submitted")),
            submitted_at=datetime.utcnow(),
            notes=form.get("notes", ""),
        )
        session.add(invoice)
        await session.flush()
        invoice_id = invoice.id

    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(request: Request, invoice_id: int):
    """Invoice detail with approve/reject/paid actions"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(
                selectinload(Invoice.vendor_ref),
                selectinload(Invoice.property_ref),
                selectinload(Invoice.work_order_ref),
                selectinload(Invoice.project_ref),
            )
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            return RedirectResponse(url="/invoices", status_code=303)

    return templates.TemplateResponse("invoices/detail.html", {
        "request": request,
        "user": user,
        "invoice": invoice,
    })


@router.post("/{invoice_id}/approve")
async def invoice_approve(request: Request, invoice_id: int):
    """Approve an invoice"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice:
            invoice.status = InvoiceStatus.APPROVED
            invoice.approved_at = datetime.utcnow()
            if form.get("notes"):
                invoice.notes = form["notes"]

    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/reject")
async def invoice_reject(request: Request, invoice_id: int):
    """Reject an invoice"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice:
            invoice.status = InvoiceStatus.REJECTED
            invoice.rejected_at = datetime.utcnow()
            invoice.notes = form.get("notes", "")

    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/paid")
async def invoice_mark_paid(request: Request, invoice_id: int):
    """Mark invoice as paid"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Invoice).where(Invoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = datetime.utcnow()
            if form.get("notes"):
                invoice.notes = form["notes"]

    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)
