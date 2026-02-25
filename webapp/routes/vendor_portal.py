"""Vendor Portal routes"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Vendor, WorkOrder, WorkOrderPhoto, WorkOrderStatus,
    Property, Invoice, InvoiceStatus, SMSMessage, MessageDirection,
)
from webapp.auth.vendor_auth import get_current_vendor, login_vendor, logout_vendor
from webapp.services.vendor_verification_service import (
    send_vendor_verification_code, verify_vendor_code,
)

router = APIRouter(tags=["vendor-portal"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Upload directories
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
WO_UPLOAD_DIR = Path(UPLOAD_BASE) / "work_orders"
WO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
INVOICE_UPLOAD_DIR = Path(UPLOAD_BASE) / "invoices"
INVOICE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Authentication
# =============================================================================

@router.get("/login", response_class=HTMLResponse)
async def vendor_login(request: Request):
    """Phone number input form"""
    vendor = await get_current_vendor(request)
    if vendor:
        return RedirectResponse(url="/vendor", status_code=303)
    return templates.TemplateResponse("vendor/login.html", {"request": request})


@router.post("/login")
async def vendor_login_submit(request: Request):
    """Send SMS verification code"""
    form = await request.form()
    phone = form.get("phone", "").strip()

    if not phone:
        return templates.TemplateResponse("vendor/login.html", {
            "request": request,
            "error": "Please enter your phone number.",
        })

    result = await send_vendor_verification_code(phone)

    if not result["success"]:
        return templates.TemplateResponse("vendor/login.html", {
            "request": request,
            "error": result["error"],
            "phone": phone,
        })

    request.session["vendor_phone"] = phone
    return RedirectResponse(url="/vendor/verify", status_code=303)


@router.get("/verify", response_class=HTMLResponse)
async def vendor_verify(request: Request):
    """Code input form"""
    phone = request.session.get("vendor_phone")
    if not phone:
        return RedirectResponse(url="/vendor/login", status_code=303)
    return templates.TemplateResponse("vendor/verify.html", {
        "request": request,
        "phone": phone,
    })


@router.post("/verify")
async def vendor_verify_submit(request: Request):
    """Verify code and create vendor session"""
    form = await request.form()
    code = form.get("code", "").strip()
    phone = request.session.get("vendor_phone")

    if not phone:
        return RedirectResponse(url="/vendor/login", status_code=303)

    if not code:
        return templates.TemplateResponse("vendor/verify.html", {
            "request": request,
            "phone": phone,
            "error": "Please enter the verification code.",
        })

    result = await verify_vendor_code(phone, code)

    if not result["success"]:
        return templates.TemplateResponse("vendor/verify.html", {
            "request": request,
            "phone": phone,
            "error": result["error"],
        })

    login_vendor(request, result["vendor"])
    request.session.pop("vendor_phone", None)
    return RedirectResponse(url="/vendor", status_code=303)


@router.get("/logout")
async def vendor_logout(request: Request):
    """Clear vendor session"""
    logout_vendor(request)
    return RedirectResponse(url="/vendor/login", status_code=303)


# =============================================================================
# Dashboard
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def vendor_dashboard(request: Request):
    """Vendor dashboard"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        # Active work orders count
        wo_result = await session.execute(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.vendor_id == vendor["id"],
                WorkOrder.status.in_([
                    WorkOrderStatus.ASSIGNED,
                    WorkOrderStatus.IN_PROGRESS,
                ])
            )
        )
        active_wo_count = wo_result.scalar() or 0

        # Pending invoices count
        inv_result = await session.execute(
            select(func.count(Invoice.id)).where(
                Invoice.vendor_id == vendor["id"],
                Invoice.status == InvoiceStatus.SUBMITTED,
            )
        )
        pending_invoices = inv_result.scalar() or 0

        # Total earned (paid invoices)
        paid_result = await session.execute(
            select(func.sum(Invoice.amount)).where(
                Invoice.vendor_id == vendor["id"],
                Invoice.status == InvoiceStatus.PAID,
            )
        )
        total_earned = paid_result.scalar() or 0

        # Upcoming scheduled work (next 5)
        upcoming_result = await session.execute(
            select(WorkOrder)
            .where(
                WorkOrder.vendor_id == vendor["id"],
                WorkOrder.scheduled_date != None,
                WorkOrder.status.in_([WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS]),
            )
            .options(selectinload(WorkOrder.property_ref))
            .order_by(WorkOrder.scheduled_date)
            .limit(5)
        )
        upcoming_work = upcoming_result.scalars().all()

        # Recent invoices (last 5)
        recent_inv_result = await session.execute(
            select(Invoice)
            .where(Invoice.vendor_id == vendor["id"])
            .options(selectinload(Invoice.property_ref))
            .order_by(desc(Invoice.created_at))
            .limit(5)
        )
        recent_invoices = recent_inv_result.scalars().all()

    return templates.TemplateResponse("vendor/dashboard.html", {
        "request": request,
        "vendor": vendor,
        "active_wo_count": active_wo_count,
        "pending_invoices": pending_invoices,
        "total_earned": total_earned,
        "upcoming_work": upcoming_work,
        "recent_invoices": recent_invoices,
    })


# =============================================================================
# Work Orders
# =============================================================================

@router.get("/work-orders", response_class=HTMLResponse)
async def vendor_work_orders(request: Request):
    """List vendor's assigned work orders"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.vendor_id == vendor["id"])
            .options(
                selectinload(WorkOrder.property_ref),
                selectinload(WorkOrder.photos),
            )
            .order_by(desc(WorkOrder.created_at))
        )
        work_orders = result.scalars().all()

    return templates.TemplateResponse("vendor/work_orders.html", {
        "request": request,
        "vendor": vendor,
        "work_orders": work_orders,
    })


@router.get("/work-orders/{wo_id}", response_class=HTMLResponse)
async def vendor_work_order_detail(request: Request, wo_id: int):
    """View work order detail (read-only + photo upload)"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(
                WorkOrder.id == wo_id,
                WorkOrder.vendor_id == vendor["id"],
            )
            .options(
                selectinload(WorkOrder.property_ref),
                selectinload(WorkOrder.photos),
                selectinload(WorkOrder.tenant_ref),
            )
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/vendor/work-orders", status_code=303)

    return templates.TemplateResponse("vendor/work_order_detail.html", {
        "request": request,
        "vendor": vendor,
        "wo": wo,
    })


@router.post("/work-orders/{wo_id}/photos/upload")
async def vendor_photo_upload(request: Request, wo_id: int, photo: UploadFile = File(...)):
    """Upload photo for a work order (vendor)"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if photo.content_type not in allowed_types:
        return JSONResponse({"error": "Invalid file type"}, status_code=400)

    contents = await photo.read()
    if len(contents) > 10 * 1024 * 1024:  # 10MB
        return JSONResponse({"error": "File too large. Max 10MB."}, status_code=400)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder).where(
                WorkOrder.id == wo_id,
                WorkOrder.vendor_id == vendor["id"],
            )
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return JSONResponse({"error": "Work order not found"}, status_code=404)

        ext = Path(photo.filename).suffix.lower() or ".jpg"
        filename = f"wo_{wo_id}_vendor_{uuid.uuid4().hex[:8]}{ext}"
        filepath = WO_UPLOAD_DIR / filename

        with open(filepath, "wb") as f:
            f.write(contents)

        photo_record = WorkOrderPhoto(
            work_order_id=wo_id,
            url=f"/uploads/work_orders/{filename}",
            uploaded_by_tenant=False,
        )
        session.add(photo_record)
        await session.flush()

        return JSONResponse({"success": True, "photo_id": photo_record.id, "url": photo_record.url})


# =============================================================================
# Invoices
# =============================================================================

@router.get("/invoices", response_class=HTMLResponse)
async def vendor_invoices(request: Request):
    """List vendor's invoices"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Invoice)
            .where(Invoice.vendor_id == vendor["id"])
            .options(selectinload(Invoice.property_ref))
            .order_by(desc(Invoice.created_at))
        )
        invoices = result.scalars().all()

    return templates.TemplateResponse("vendor/invoices.html", {
        "request": request,
        "vendor": vendor,
        "invoices": invoices,
    })


@router.get("/invoices/new", response_class=HTMLResponse)
async def vendor_invoice_form(request: Request):
    """New invoice form"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        # Get properties where vendor has work orders
        wo_result = await session.execute(
            select(WorkOrder.property_id)
            .where(WorkOrder.vendor_id == vendor["id"])
            .distinct()
        )
        property_ids = [row[0] for row in wo_result.all()]

        properties = []
        if property_ids:
            prop_result = await session.execute(
                select(Property).where(Property.id.in_(property_ids))
            )
            properties = prop_result.scalars().all()

        # Get vendor's work orders for optional linking
        work_orders_result = await session.execute(
            select(WorkOrder)
            .where(
                WorkOrder.vendor_id == vendor["id"],
                WorkOrder.status.in_([
                    WorkOrderStatus.ASSIGNED,
                    WorkOrderStatus.IN_PROGRESS,
                    WorkOrderStatus.COMPLETED,
                ])
            )
            .options(selectinload(WorkOrder.property_ref))
            .order_by(desc(WorkOrder.created_at))
        )
        work_orders = work_orders_result.scalars().all()

    return templates.TemplateResponse("vendor/invoice_form.html", {
        "request": request,
        "vendor": vendor,
        "properties": properties,
        "work_orders": work_orders,
    })


@router.post("/invoices/new")
async def vendor_invoice_submit(request: Request):
    """Submit a new invoice"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    form = await request.form()
    title = form.get("title", "").strip()
    amount = form.get("amount", "").strip()
    description = form.get("description", "").strip()
    property_id = form.get("property_id")
    work_order_id = form.get("work_order_id") or None
    file: UploadFile = form.get("file")

    if not title or not amount or not property_id:
        return RedirectResponse(url="/vendor/invoices/new?error=missing_fields", status_code=303)

    try:
        amount_val = float(amount)
    except ValueError:
        return RedirectResponse(url="/vendor/invoices/new?error=invalid_amount", status_code=303)

    # Handle file upload
    file_url = None
    if file and file.filename:
        allowed_types = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }
        if file.content_type not in allowed_types:
            return RedirectResponse(url="/vendor/invoices/new?error=invalid_file", status_code=303)

        contents = await file.read()
        if len(contents) > 20 * 1024 * 1024:  # 20MB
            return RedirectResponse(url="/vendor/invoices/new?error=file_too_large", status_code=303)

        ext = allowed_types.get(file.content_type, ".pdf")
        filename = f"invoice_{uuid.uuid4().hex[:12]}{ext}"
        filepath = INVOICE_UPLOAD_DIR / filename

        with open(filepath, "wb") as f:
            f.write(contents)

        file_url = f"/uploads/invoices/{filename}"

    async with get_session() as session:
        # Verify property belongs to vendor's scope
        wo_check = await session.execute(
            select(WorkOrder.id).where(
                WorkOrder.vendor_id == vendor["id"],
                WorkOrder.property_id == int(property_id),
            ).limit(1)
        )
        if not wo_check.scalar_one_or_none():
            return RedirectResponse(url="/vendor/invoices/new?error=invalid_property", status_code=303)

        invoice = Invoice(
            vendor_id=vendor["id"],
            property_id=int(property_id),
            work_order_id=int(work_order_id) if work_order_id else None,
            title=title,
            description=description,
            amount=amount_val,
            file_url=file_url,
            status=InvoiceStatus.SUBMITTED,
            submitted_at=datetime.utcnow(),
        )
        session.add(invoice)
        await session.flush()
        invoice_id = invoice.id

    return RedirectResponse(url=f"/vendor/invoices/{invoice_id}", status_code=303)


@router.get("/invoices/{inv_id}", response_class=HTMLResponse)
async def vendor_invoice_detail(request: Request, inv_id: int):
    """View invoice detail"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Invoice)
            .where(
                Invoice.id == inv_id,
                Invoice.vendor_id == vendor["id"],
            )
            .options(
                selectinload(Invoice.property_ref),
                selectinload(Invoice.work_order_ref),
            )
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            return RedirectResponse(url="/vendor/invoices", status_code=303)

    return templates.TemplateResponse("vendor/invoice_detail.html", {
        "request": request,
        "vendor": vendor,
        "invoice": invoice,
    })


# =============================================================================
# Messages
# =============================================================================

def _normalize_phone(phone: str):
    """Normalize phone number to E.164 format"""
    if not phone:
        return None
    digits = ''.join(c for c in phone if c.isdigit() or c == '+')
    if not digits:
        return None
    if digits.startswith('+'):
        return digits
    elif digits.startswith('1') and len(digits) == 11:
        return f"+{digits}"
    elif len(digits) == 10:
        return f"+1{digits}"
    return f"+{digits}"


@router.get("/messages", response_class=HTMLResponse)
async def vendor_messages(request: Request):
    """Vendor messaging - chat with PM"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    return templates.TemplateResponse("vendor/messages.html", {
        "request": request,
        "vendor": vendor,
    })


@router.get("/messages/conversation")
async def vendor_messages_conversation(request: Request):
    """API: Get vendor's message history"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with get_session() as session:
        vendor_result = await session.execute(
            select(Vendor).where(Vendor.id == vendor["id"])
        )
        vendor_record = vendor_result.scalar_one_or_none()

        if not vendor_record or not vendor_record.phone:
            return JSONResponse({"messages": [], "error": "No phone number on file"})

        vendor_phone = _normalize_phone(vendor_record.phone)

        from sqlalchemy import or_
        result = await session.execute(
            select(SMSMessage)
            .where(
                or_(
                    SMSMessage.from_number == vendor_phone,
                    SMSMessage.to_number == vendor_phone,
                )
            )
            .order_by(SMSMessage.created_at.asc())
        )
        messages = result.scalars().all()

        return JSONResponse({
            "messages": [
                {
                    "id": msg.id,
                    "body": msg.body,
                    "direction": msg.direction.value,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                for msg in messages
            ]
        })


@router.post("/messages/send")
async def vendor_messages_send(request: Request):
    """API: Send a message from vendor to PM"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    form = await request.form()
    body = form.get("message", "").strip()
    if not body:
        return JSONResponse({"error": "Message cannot be empty"}, status_code=400)

    async with get_session() as session:
        vendor_result = await session.execute(
            select(Vendor).where(Vendor.id == vendor["id"])
        )
        vendor_record = vendor_result.scalar_one_or_none()

        if not vendor_record or not vendor_record.phone:
            return JSONResponse({"error": "No phone number on file"}, status_code=400)

        vendor_phone = _normalize_phone(vendor_record.phone)

        from webapp.services.twilio_service import twilio_service
        our_phone = _normalize_phone(twilio_service.from_number) if twilio_service.from_number else "vendor-portal"

        sms_message = SMSMessage(
            from_number=vendor_phone,
            to_number=our_phone,
            body=f"[Vendor: {vendor['name']}] {body}",
            direction=MessageDirection.INBOUND,
            status="received",
            created_at=datetime.utcnow(),
        )
        session.add(sms_message)
        await session.flush()

        return JSONResponse({"success": True, "message_id": sms_message.id})


# =============================================================================
# Calendar
# =============================================================================

@router.get("/calendar", response_class=HTMLResponse)
async def vendor_calendar(request: Request):
    """Calendar view of scheduled work"""
    vendor = await get_current_vendor(request)
    if not vendor:
        return RedirectResponse(url="/vendor/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(
                WorkOrder.vendor_id == vendor["id"],
                WorkOrder.scheduled_date != None,
            )
            .options(selectinload(WorkOrder.property_ref))
            .order_by(WorkOrder.scheduled_date)
        )
        work_orders = result.scalars().all()

    # Build events list for calendar
    events = []
    for wo in work_orders:
        events.append({
            "id": wo.id,
            "title": wo.title,
            "date": wo.scheduled_date.isoformat() if wo.scheduled_date else None,
            "status": wo.status.value,
            "property": wo.property_ref.address if wo.property_ref else "Unknown",
            "priority": wo.priority.value if wo.priority else "normal",
        })

    return templates.TemplateResponse("vendor/calendar.html", {
        "request": request,
        "vendor": vendor,
        "events": events,
    })
