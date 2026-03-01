"""Maintenance / Work Order routes"""

import logging
import os
import uuid
from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    WorkOrder, WorkOrderPhoto, WorkOrderStatus, WorkOrderPriority,
    WorkOrderCategory, Vendor, Property, Tenant
)
from webapp.auth.dependencies import get_current_user
from webapp.services.twilio_service import twilio_service
from webapp.services.telegram_service import telegram_service

router = APIRouter(tags=["maintenance"])

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Upload directory for work order photos
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_BASE) / "work_orders"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def _notify_vendor_sms(vendor_id: int, wo, session):
    """Send SMS to vendor about a work order assignment"""
    try:
        result = await session.execute(
            select(Vendor).where(Vendor.id == vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if not vendor or not vendor.phone:
            return False

        # Always query property by ID (avoid lazy-load issues in async)
        prop_addr = ""
        if wo.property_id:
            prop_result = await session.execute(
                select(Property).where(Property.id == wo.property_id)
            )
            prop = prop_result.scalar_one_or_none()
            prop_addr = prop.address if prop else ""

        priority_label = wo.priority.value.title() if wo.priority else "Normal"
        scheduled = wo.scheduled_date.strftime('%b %d, %Y') if wo.scheduled_date else "TBD"

        msg = (
            f"Blue Deer - New Work Order Assigned\n\n"
            f"Title: {wo.title}\n"
            f"Property: {prop_addr}\n"
            f"Priority: {priority_label}\n"
            f"Scheduled: {scheduled}\n"
        )
        if wo.description:
            desc_short = wo.description[:100] + ("..." if len(wo.description) > 100 else "")
            msg += f"Details: {desc_short}\n"
        msg += f"\nView in portal: https://bluedeer.space/vendor/work-orders/{wo.id}"

        sms_result = await twilio_service.send_sms(vendor.phone, msg)
        if sms_result.success:
            logger.info(f"Vendor SMS sent to {vendor.name} for WO #{wo.id}")
        else:
            logger.error(f"Failed to SMS vendor {vendor.name}: {sms_result.error_message}")
        return sms_result.success
    except Exception as e:
        logger.error(f"Error sending vendor SMS: {e}")
        return False


@router.get("/", response_class=HTMLResponse)
async def list_work_orders(
    request: Request,
    status: str = None,
    priority: str = None,
    property_id: int = None,
    category: str = None
):
    """List work orders with filters"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(WorkOrder)
            .options(
                selectinload(WorkOrder.property_ref),
                selectinload(WorkOrder.tenant_ref),
                selectinload(WorkOrder.vendor_ref),
            )
        )

        if status:
            query = query.where(WorkOrder.status == WorkOrderStatus(status))
        if priority:
            query = query.where(WorkOrder.priority == WorkOrderPriority(priority))
        if property_id:
            query = query.where(WorkOrder.property_id == property_id)
        if category:
            query = query.where(WorkOrder.category == WorkOrderCategory(category))

        query = query.order_by(desc(WorkOrder.created_at))
        result = await session.execute(query)
        work_orders = result.scalars().all()

        # Get properties for filter dropdown
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        # Counts by status
        for s in WorkOrderStatus:
            count_result = await session.execute(
                select(func.count(WorkOrder.id)).where(WorkOrder.status == s)
            )
            setattr(s, '_count', count_result.scalar() or 0)

    return templates.TemplateResponse(
        "maintenance/list.html",
        {
            "request": request,
            "user": user,
            "work_orders": work_orders,
            "properties": properties,
            "statuses": WorkOrderStatus,
            "priorities": WorkOrderPriority,
            "categories": WorkOrderCategory,
            "filter_status": status,
            "filter_priority": priority,
            "filter_property_id": property_id,
            "filter_category": category,
        }
    )


# =============================================================================
# Vendor Management (must be above /{wo_id} routes to avoid path conflicts)
# =============================================================================

@router.get("/vendors", response_class=HTMLResponse)
async def list_vendors(request: Request):
    """Vendor directory"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Vendor).order_by(Vendor.name)
        )
        vendors = result.scalars().all()

    return templates.TemplateResponse(
        "maintenance/vendors.html",
        {"request": request, "user": user, "vendors": vendors}
    )


@router.get("/vendors/new", response_class=HTMLResponse)
async def new_vendor_form(request: Request):
    """Add vendor form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "maintenance/vendor_form.html",
        {"request": request, "user": user, "vendor": None}
    )


@router.post("/vendors/new")
async def create_vendor(request: Request):
    """Create a new vendor"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        vendor = Vendor(
            name=form["name"],
            phone=form.get("phone", ""),
            email=form.get("email", ""),
            specialty=form.get("specialty", ""),
            company=form.get("company", ""),
            notes=form.get("notes", ""),
        )
        session.add(vendor)

    return RedirectResponse(url="/maintenance/vendors", status_code=303)


@router.get("/vendors/{vendor_id}/edit", response_class=HTMLResponse)
async def edit_vendor_form(request: Request, vendor_id: int):
    """Edit vendor form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Vendor).where(Vendor.id == vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if not vendor:
            return RedirectResponse(url="/maintenance/vendors", status_code=303)

    return templates.TemplateResponse(
        "maintenance/vendor_form.html",
        {"request": request, "user": user, "vendor": vendor}
    )


@router.post("/vendors/{vendor_id}/edit")
async def update_vendor(request: Request, vendor_id: int):
    """Update a vendor"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Vendor).where(Vendor.id == vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if not vendor:
            return RedirectResponse(url="/maintenance/vendors", status_code=303)

        vendor.name = form["name"]
        vendor.phone = form.get("phone", "")
        vendor.email = form.get("email", "")
        vendor.specialty = form.get("specialty", "")
        vendor.company = form.get("company", "")
        vendor.notes = form.get("notes", "")
        vendor.is_active = form.get("is_active") == "on"
        vendor.updated_at = datetime.utcnow()

    return RedirectResponse(url="/maintenance/vendors", status_code=303)


# =============================================================================
# Work Order CRUD
# =============================================================================

@router.get("/new", response_class=HTMLResponse)
async def new_work_order_form(request: Request):
    """Create work order form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        tenants_result = await session.execute(
            select(Tenant).where(Tenant.is_active == True).order_by(Tenant.name)
        )
        tenants = tenants_result.scalars().all()

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "maintenance/form.html",
        {
            "request": request,
            "user": user,
            "work_order": None,
            "properties": properties,
            "tenants": tenants,
            "vendors": vendors,
            "priorities": WorkOrderPriority,
            "categories": WorkOrderCategory,
        }
    )


@router.post("/new")
async def create_work_order(request: Request):
    """Create a new work order"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    property_id_str = form.get("property_id", "").strip()
    tenant_id_str = form.get("tenant_id", "").strip()
    vendor_id_str = form.get("vendor_id", "").strip()
    scheduled_str = form.get("scheduled_date", "").strip()
    cost_str = form.get("estimated_cost", "").strip()

    if not property_id_str:
        return RedirectResponse(url="/maintenance/new", status_code=303)

    async with get_session() as session:
        wo = WorkOrder(
            property_id=int(property_id_str),
            tenant_id=int(tenant_id_str) if tenant_id_str else None,
            vendor_id=int(vendor_id_str) if vendor_id_str else None,
            title=form["title"],
            description=form.get("description", ""),
            category=WorkOrderCategory(form.get("category", "general")),
            priority=WorkOrderPriority(form.get("priority", "normal")),
            status=WorkOrderStatus.NEW,
            unit_area=form.get("unit_area", ""),
            scheduled_date=datetime.strptime(scheduled_str, "%Y-%m-%d").date() if scheduled_str else None,
            estimated_cost=float(cost_str) if cost_str else None,
        )
        session.add(wo)
        await session.flush()
        wo_id = wo.id

        # Send SMS to vendor if assigned and checkbox checked
        if wo.vendor_id and form.get("notify_vendor"):
            await _notify_vendor_sms(wo.vendor_id, wo, session)

        # Send Telegram notification via Blue Deer bot
        try:
            # Load property address for the message
            prop_result = await session.execute(
                select(Property).where(Property.id == wo.property_id)
            )
            prop = prop_result.scalar_one_or_none()
            addr = prop.address if prop else "Unknown"

            # Priority badge
            priority_icons = {
                WorkOrderPriority.EMERGENCY: ("🚨", "EMERGENCY"),
                WorkOrderPriority.HIGH: ("🔴", "High"),
                WorkOrderPriority.NORMAL: ("🟡", "Normal"),
                WorkOrderPriority.LOW: ("🟢", "Low"),
            }
            icon, label = priority_icons.get(wo.priority, ("🟡", "Normal"))
            category = wo.category.value.replace('_', ' ').title() if wo.category else "General"

            msg = f"🔧 *New Work Order Created*\n\n"
            msg += f"{icon} *{wo.title}*\n"
            msg += f"  📍 {addr}"
            if wo.unit_area:
                msg += f", {wo.unit_area}"
            msg += "\n"
            msg += f"  📋 {category} • Priority: {label}\n"
            if wo.description:
                desc = wo.description[:120]
                if len(wo.description) > 120:
                    desc += "..."
                msg += f"  💬 _{desc}_\n"
            if wo.estimated_cost:
                msg += f"  💰 Est. cost: ${wo.estimated_cost:.2f}\n"
            if wo.scheduled_date:
                msg += f"  📅 Scheduled: {wo.scheduled_date.strftime('%b %d, %Y')}\n"

            await telegram_service.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to send work order Telegram alert: {e}")

    return RedirectResponse(url=f"/maintenance/{wo_id}", status_code=303)


@router.get("/{wo_id}", response_class=HTMLResponse)
async def work_order_detail(request: Request, wo_id: int):
    """Work order detail view"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.id == wo_id)
            .options(
                selectinload(WorkOrder.property_ref),
                selectinload(WorkOrder.tenant_ref),
                selectinload(WorkOrder.vendor_ref),
                selectinload(WorkOrder.photos),
            )
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "maintenance/detail.html",
        {
            "request": request,
            "user": user,
            "wo": wo,
            "vendors": vendors,
            "statuses": WorkOrderStatus,
            "priorities": WorkOrderPriority,
        }
    )


@router.get("/{wo_id}/edit", response_class=HTMLResponse)
async def edit_work_order_form(request: Request, wo_id: int):
    """Edit work order form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.id == wo_id)
            .options(
                selectinload(WorkOrder.property_ref),
                selectinload(WorkOrder.tenant_ref),
                selectinload(WorkOrder.vendor_ref),
            )
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        tenants_result = await session.execute(
            select(Tenant).where(Tenant.is_active == True).order_by(Tenant.name)
        )
        tenants = tenants_result.scalars().all()

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "maintenance/form.html",
        {
            "request": request,
            "user": user,
            "work_order": wo,
            "properties": properties,
            "tenants": tenants,
            "vendors": vendors,
            "priorities": WorkOrderPriority,
            "categories": WorkOrderCategory,
        }
    )


@router.post("/{wo_id}/edit")
async def update_work_order(request: Request, wo_id: int):
    """Update a work order"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.id == wo_id)
            .options(selectinload(WorkOrder.property_ref))
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        old_vendor_id = wo.vendor_id
        tenant_str = form.get("tenant_id", "").strip()
        vendor_str = form.get("vendor_id", "").strip()
        sched_str = form.get("scheduled_date", "").strip()
        est_str = form.get("estimated_cost", "").strip()
        act_str = form.get("actual_cost", "").strip()
        new_vendor_id = int(vendor_str) if vendor_str else None

        wo.property_id = int(form["property_id"])
        wo.tenant_id = int(tenant_str) if tenant_str else None
        wo.vendor_id = new_vendor_id
        wo.title = form["title"]
        wo.description = form.get("description", "")
        wo.category = WorkOrderCategory(form.get("category", "general"))
        wo.priority = WorkOrderPriority(form.get("priority", "normal"))
        wo.unit_area = form.get("unit_area", "")
        wo.scheduled_date = datetime.strptime(sched_str, "%Y-%m-%d").date() if sched_str else None
        wo.estimated_cost = float(est_str) if est_str else None
        wo.actual_cost = float(act_str) if act_str else None
        wo.resolution_notes = form.get("resolution_notes", "")

        if form.get("status"):
            new_status = WorkOrderStatus(form["status"])
            wo.status = new_status
            if new_status == WorkOrderStatus.COMPLETED and not wo.completed_date:
                wo.completed_date = date.today()

        wo.updated_at = datetime.utcnow()

        # Notify vendor if newly assigned or reassigned and checkbox checked
        if new_vendor_id and form.get("notify_vendor") and new_vendor_id != old_vendor_id:
            await _notify_vendor_sms(new_vendor_id, wo, session)

    return RedirectResponse(url=f"/maintenance/{wo_id}", status_code=303)


@router.post("/{wo_id}/notify-vendor")
async def notify_vendor(request: Request, wo_id: int):
    """Manually send SMS notification to assigned vendor"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.id == wo_id)
            .options(selectinload(WorkOrder.property_ref))
        )
        wo = result.scalar_one_or_none()
        if not wo or not wo.vendor_id:
            return RedirectResponse(url=f"/maintenance/{wo_id}", status_code=303)

        sent = await _notify_vendor_sms(wo.vendor_id, wo, session)

    return RedirectResponse(url=f"/maintenance/{wo_id}?sms={'sent' if sent else 'failed'}", status_code=303)


@router.post("/{wo_id}/assign-vendor")
async def assign_vendor(request: Request, wo_id: int):
    """Quick vendor assignment from detail page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    vendor_str = form.get("vendor_id", "").strip()
    new_vendor_id = int(vendor_str) if vendor_str else None

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        old_vendor_id = wo.vendor_id
        wo.vendor_id = new_vendor_id
        wo.updated_at = datetime.utcnow()

        # Auto-set status to assigned when a vendor is assigned and status is still new
        if new_vendor_id and wo.status == WorkOrderStatus.NEW:
            wo.status = WorkOrderStatus.ASSIGNED

        # SMS notify vendor if requested and vendor changed
        sms_param = ""
        if new_vendor_id and form.get("notify_vendor") and new_vendor_id != old_vendor_id:
            sent = await _notify_vendor_sms(new_vendor_id, wo, session)
            sms_param = f"&sms={'sent' if sent else 'failed'}"

    return RedirectResponse(url=f"/maintenance/{wo_id}?assigned=1{sms_param}", status_code=303)


@router.post("/{wo_id}/status")
async def update_work_order_status(request: Request, wo_id: int):
    """Quick status change"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    new_status = form.get("status")

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        wo.status = WorkOrderStatus(new_status)
        wo.updated_at = datetime.utcnow()
        if WorkOrderStatus(new_status) == WorkOrderStatus.COMPLETED and not wo.completed_date:
            wo.completed_date = date.today()

    return RedirectResponse(url=f"/maintenance/{wo_id}", status_code=303)


@router.post("/{wo_id}/photos/upload")
async def upload_work_order_photo(
    request: Request,
    wo_id: int,
    photo: UploadFile = File(...)
):
    """Upload a photo for a work order"""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if photo.content_type not in allowed_types:
        return JSONResponse({"error": "Invalid file type. Use JPG, PNG, WebP, or GIF."}, status_code=400)

    contents = await photo.read()
    if len(contents) > 10 * 1024 * 1024:
        return JSONResponse({"error": "File too large. Max 10MB."}, status_code=400)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return JSONResponse({"error": "Work order not found"}, status_code=404)

        ext = Path(photo.filename).suffix.lower() or ".jpg"
        filename = f"wo_{wo_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = UPLOAD_DIR / filename

        with open(filepath, "wb") as f:
            f.write(contents)

        photo_record = WorkOrderPhoto(
            work_order_id=wo_id,
            url=f"/uploads/work_orders/{filename}",
        )
        session.add(photo_record)
        await session.flush()

        return JSONResponse({
            "success": True,
            "photo_id": photo_record.id,
            "url": photo_record.url,
        })


@router.post("/{wo_id}/delete")
async def delete_work_order(request: Request, wo_id: int):
    """Delete a work order and its photos"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.id == wo_id)
            .options(selectinload(WorkOrder.photos))
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        # Delete photo files from disk
        for photo in wo.photos:
            if photo.url:
                filepath = Path(UPLOAD_BASE) / photo.url.lstrip("/uploads/")
                if filepath.exists():
                    filepath.unlink()
            await session.delete(photo)

        await session.delete(wo)

    return RedirectResponse(url="/maintenance", status_code=303)


@router.post("/{wo_id}/photos/{photo_id}/delete")
async def delete_work_order_photo(request: Request, wo_id: int, photo_id: int):
    """Delete a work order photo"""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    async with get_session() as session:
        result = await session.execute(
            select(WorkOrderPhoto).where(
                WorkOrderPhoto.id == photo_id,
                WorkOrderPhoto.work_order_id == wo_id
            )
        )
        photo = result.scalar_one_or_none()
        if not photo:
            return JSONResponse({"error": "Photo not found"}, status_code=404)

        # Delete file from disk
        if photo.url:
            filepath = Path(UPLOAD_BASE) / photo.url.lstrip("/uploads/")
            if filepath.exists():
                filepath.unlink()

        await session.delete(photo)

    return JSONResponse({"success": True})
