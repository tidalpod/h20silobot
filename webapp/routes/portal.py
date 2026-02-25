"""Tenant Portal routes"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Tenant, Property, WorkOrder, WorkOrderPhoto, WorkOrderStatus,
    WorkOrderPriority, WorkOrderCategory, LeaseDocument, LeaseStatus,
    WaterBill, SMSMessage, MessageDirection,
)
from webapp.auth.tenant_auth import get_current_tenant, login_tenant, logout_tenant
from webapp.services.verification_service import send_verification_code, verify_code

router = APIRouter(tags=["portal"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Upload directory for tenant-submitted photos
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_BASE) / "work_orders"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Authentication
# =============================================================================

@router.get("/login", response_class=HTMLResponse)
async def portal_login(request: Request):
    """Phone number input form"""
    tenant = await get_current_tenant(request)
    if tenant:
        return RedirectResponse(url="/portal", status_code=303)
    return templates.TemplateResponse("portal/login.html", {"request": request})


@router.post("/login")
async def portal_login_submit(request: Request):
    """Send SMS verification code"""
    form = await request.form()
    phone = form.get("phone", "").strip()

    if not phone:
        return templates.TemplateResponse("portal/login.html", {
            "request": request,
            "error": "Please enter your phone number.",
        })

    result = await send_verification_code(phone)

    if not result["success"]:
        return templates.TemplateResponse("portal/login.html", {
            "request": request,
            "error": result["error"],
            "phone": phone,
        })

    # Store phone in session for verification step
    request.session["portal_phone"] = phone
    return RedirectResponse(url="/portal/verify", status_code=303)


@router.get("/verify", response_class=HTMLResponse)
async def portal_verify(request: Request):
    """Code input form"""
    phone = request.session.get("portal_phone")
    if not phone:
        return RedirectResponse(url="/portal/login", status_code=303)
    return templates.TemplateResponse("portal/verify.html", {
        "request": request,
        "phone": phone,
    })


@router.post("/verify")
async def portal_verify_submit(request: Request):
    """Verify the code and create tenant session"""
    form = await request.form()
    code = form.get("code", "").strip()
    phone = request.session.get("portal_phone")

    if not phone:
        return RedirectResponse(url="/portal/login", status_code=303)

    if not code:
        return templates.TemplateResponse("portal/verify.html", {
            "request": request,
            "phone": phone,
            "error": "Please enter the verification code.",
        })

    result = await verify_code(phone, code)

    if not result["success"]:
        return templates.TemplateResponse("portal/verify.html", {
            "request": request,
            "phone": phone,
            "error": result["error"],
        })

    # Log tenant in
    login_tenant(request, result["tenant"])
    request.session.pop("portal_phone", None)
    return RedirectResponse(url="/portal", status_code=303)


@router.get("/logout")
async def portal_logout(request: Request):
    """Clear tenant session"""
    logout_tenant(request)
    return RedirectResponse(url="/portal/login", status_code=303)


# =============================================================================
# Dashboard
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def portal_dashboard(request: Request):
    """Tenant dashboard"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    async with get_session() as session:
        # Get property info
        prop_result = await session.execute(
            select(Property).where(Property.id == tenant["property_id"])
        )
        prop = prop_result.scalar_one_or_none()

        # Open work orders count
        wo_result = await session.execute(
            select(WorkOrder).where(
                WorkOrder.property_id == tenant["property_id"],
                WorkOrder.status.in_([WorkOrderStatus.NEW, WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS])
            )
        )
        open_requests = len(wo_result.scalars().all())

        # Active lease
        lease_result = await session.execute(
            select(LeaseDocument).where(
                LeaseDocument.property_id == tenant["property_id"],
                LeaseDocument.status == LeaseStatus.ACTIVE,
            ).order_by(desc(LeaseDocument.created_at)).limit(1)
        )
        active_lease = lease_result.scalar_one_or_none()

        # Latest water bill
        if prop:
            bill_result = await session.execute(
                select(WaterBill).where(
                    WaterBill.property_id == tenant["property_id"]
                ).order_by(desc(WaterBill.statement_date)).limit(1)
            )
            latest_bill = bill_result.scalar_one_or_none()
        else:
            latest_bill = None

    # Rent balance due (safe import — won't fail if service has issues)
    rent_due = None
    try:
        from webapp.services.payment_service import calculate_balance_due
        rent_due = await calculate_balance_due(tenant["id"])
    except Exception:
        pass

    return templates.TemplateResponse("portal/dashboard.html", {
        "request": request,
        "tenant": tenant,
        "property": prop,
        "open_requests": open_requests,
        "active_lease": active_lease,
        "latest_bill": latest_bill,
        "rent_due": rent_due,
    })


# =============================================================================
# Maintenance
# =============================================================================

@router.get("/maintenance", response_class=HTMLResponse)
async def portal_maintenance_list(request: Request):
    """Tenant's maintenance requests"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.property_id == tenant["property_id"])
            .options(selectinload(WorkOrder.photos))
            .order_by(desc(WorkOrder.created_at))
        )
        work_orders = result.scalars().all()

    return templates.TemplateResponse("portal/maintenance_list.html", {
        "request": request,
        "tenant": tenant,
        "work_orders": work_orders,
    })


@router.get("/maintenance/new", response_class=HTMLResponse)
async def portal_maintenance_form(request: Request):
    """Submit new maintenance request"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    return templates.TemplateResponse("portal/maintenance_form.html", {
        "request": request,
        "tenant": tenant,
        "categories": WorkOrderCategory,
    })


@router.post("/maintenance/new")
async def portal_maintenance_submit(request: Request):
    """Create maintenance request (tenant-submitted)"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        wo = WorkOrder(
            property_id=tenant["property_id"],
            tenant_id=tenant["id"],
            title=form["title"],
            description=form.get("description", ""),
            category=WorkOrderCategory(form.get("category", "general")),
            priority=WorkOrderPriority.NORMAL,
            status=WorkOrderStatus.NEW,
            unit_area=form.get("unit_area", ""),
            submitted_by_tenant=True,
        )
        session.add(wo)
        await session.flush()
        wo_id = wo.id

    return RedirectResponse(url=f"/portal/maintenance/{wo_id}", status_code=303)


@router.get("/maintenance/{wo_id}", response_class=HTMLResponse)
async def portal_maintenance_detail(request: Request, wo_id: int):
    """View maintenance request status"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(
                WorkOrder.id == wo_id,
                WorkOrder.property_id == tenant["property_id"],  # Security: scope to tenant's property
            )
            .options(selectinload(WorkOrder.photos))
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/portal/maintenance", status_code=303)

    return templates.TemplateResponse("portal/maintenance_detail.html", {
        "request": request,
        "tenant": tenant,
        "wo": wo,
    })


@router.post("/maintenance/{wo_id}/photos/upload")
async def portal_photo_upload(request: Request, wo_id: int, photo: UploadFile = File(...)):
    """Upload photo for a maintenance request (tenant)"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if photo.content_type not in allowed_types:
        return JSONResponse({"error": "Invalid file type"}, status_code=400)

    contents = await photo.read()
    if len(contents) > 5 * 1024 * 1024:  # 5MB for tenant uploads
        return JSONResponse({"error": "File too large. Max 5MB."}, status_code=400)

    async with get_session() as session:
        # Verify work order belongs to tenant's property
        result = await session.execute(
            select(WorkOrder).where(
                WorkOrder.id == wo_id,
                WorkOrder.property_id == tenant["property_id"],
            )
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return JSONResponse({"error": "Work order not found"}, status_code=404)

        ext = Path(photo.filename).suffix.lower() or ".jpg"
        filename = f"wo_{wo_id}_tenant_{uuid.uuid4().hex[:8]}{ext}"
        filepath = UPLOAD_DIR / filename

        with open(filepath, "wb") as f:
            f.write(contents)

        photo_record = WorkOrderPhoto(
            work_order_id=wo_id,
            url=f"/uploads/work_orders/{filename}",
            uploaded_by_tenant=True,
        )
        session.add(photo_record)
        await session.flush()

        return JSONResponse({"success": True, "photo_id": photo_record.id, "url": photo_record.url})


# =============================================================================
# Lease
# =============================================================================

@router.get("/lease", response_class=HTMLResponse)
async def portal_lease(request: Request):
    """View lease documents"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument)
            .where(
                LeaseDocument.property_id == tenant["property_id"],
                LeaseDocument.status != LeaseStatus.TERMINATED,
            )
            .order_by(desc(LeaseDocument.created_at))
        )
        leases = result.scalars().all()

    return templates.TemplateResponse("portal/lease.html", {
        "request": request,
        "tenant": tenant,
        "leases": leases,
    })


@router.get("/lease/{lease_id}/download")
async def portal_lease_download(request: Request, lease_id: int):
    """Download lease PDF (scoped to tenant's property)"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument).where(
                LeaseDocument.id == lease_id,
                LeaseDocument.property_id == tenant["property_id"],  # Security
            )
        )
        lease = result.scalar_one_or_none()
        if not lease:
            return RedirectResponse(url="/portal/lease", status_code=303)

        upload_base = os.environ.get("UPLOAD_PATH") or (
            "/app/uploads" if Path("/app/uploads").exists()
            else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
        )
        relative_path = lease.file_url.lstrip("/uploads/")
        filepath = Path(upload_base) / relative_path

        if not filepath.exists():
            return RedirectResponse(url="/portal/lease", status_code=303)

        return FileResponse(
            path=str(filepath),
            filename=f"{lease.title}.{lease.file_type}",
            media_type="application/octet-stream",
        )


# =============================================================================
# Bills
# =============================================================================

@router.get("/bills", response_class=HTMLResponse)
async def portal_bills(request: Request):
    """View water bills (read-only)"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WaterBill)
            .where(WaterBill.property_id == tenant["property_id"])
            .order_by(desc(WaterBill.statement_date))
        )
        bills = result.scalars().all()

    return templates.TemplateResponse("portal/bills.html", {
        "request": request,
        "tenant": tenant,
        "bills": bills,
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
async def portal_messages(request: Request):
    """Tenant messaging - chat with property management"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return RedirectResponse(url="/portal/login", status_code=303)

    return templates.TemplateResponse("portal/messages.html", {
        "request": request,
        "tenant": tenant,
    })


@router.get("/messages/conversation")
async def portal_messages_conversation(request: Request):
    """API: Get tenant's message history"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with get_session() as session:
        # Get the tenant record for phone number
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.id == tenant["id"])
        )
        tenant_record = tenant_result.scalar_one_or_none()

        if not tenant_record or not tenant_record.phone:
            return JSONResponse({"messages": [], "error": "No phone number on file"})

        tenant_phone = _normalize_phone(tenant_record.phone)

        # Get all messages for this tenant
        from sqlalchemy import or_
        result = await session.execute(
            select(SMSMessage)
            .where(
                or_(
                    SMSMessage.tenant_id == tenant["id"],
                    SMSMessage.from_number == tenant_phone,
                    SMSMessage.to_number == tenant_phone,
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
async def portal_messages_send(request: Request):
    """API: Send a message from tenant to property management"""
    tenant = await get_current_tenant(request)
    if not tenant:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    form = await request.form()
    body = form.get("message", "").strip()
    if not body:
        return JSONResponse({"error": "Message cannot be empty"}, status_code=400)

    async with get_session() as session:
        # Get tenant record for phone
        tenant_result = await session.execute(
            select(Tenant).where(Tenant.id == tenant["id"])
        )
        tenant_record = tenant_result.scalar_one_or_none()

        if not tenant_record or not tenant_record.phone:
            return JSONResponse({"error": "No phone number on file"}, status_code=400)

        tenant_phone = _normalize_phone(tenant_record.phone)

        # Get our Twilio number
        from webapp.services.twilio_service import twilio_service
        our_phone = _normalize_phone(twilio_service.from_number) if twilio_service.from_number else "portal"

        # Store as INBOUND message (tenant -> property management)
        # This way it shows up in the admin chat as a message from the tenant
        sms_message = SMSMessage(
            tenant_id=tenant["id"],
            property_id=tenant["property_id"],
            from_number=tenant_phone,
            to_number=our_phone,
            body=body,
            direction=MessageDirection.INBOUND,
            status="received",
            created_at=datetime.utcnow(),
        )
        session.add(sms_message)
        await session.flush()

        return JSONResponse({"success": True, "message_id": sms_message.id})
