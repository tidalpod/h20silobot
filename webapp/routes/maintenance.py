"""Maintenance / Work Order routes"""

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

router = APIRouter(tags=["maintenance"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Upload directory for work order photos
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_BASE) / "work_orders"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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

    async with get_session() as session:
        wo = WorkOrder(
            property_id=int(form["property_id"]),
            tenant_id=int(form["tenant_id"]) if form.get("tenant_id") else None,
            vendor_id=int(form["vendor_id"]) if form.get("vendor_id") else None,
            title=form["title"],
            description=form.get("description", ""),
            category=WorkOrderCategory(form.get("category", "general")),
            priority=WorkOrderPriority(form.get("priority", "normal")),
            status=WorkOrderStatus.NEW,
            unit_area=form.get("unit_area", ""),
            scheduled_date=datetime.strptime(form["scheduled_date"], "%Y-%m-%d").date() if form.get("scheduled_date") else None,
            estimated_cost=float(form["estimated_cost"]) if form.get("estimated_cost") else None,
        )
        session.add(wo)
        await session.flush()
        wo_id = wo.id

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
            select(WorkOrder).where(WorkOrder.id == wo_id)
        )
        wo = result.scalar_one_or_none()
        if not wo:
            return RedirectResponse(url="/maintenance", status_code=303)

        wo.property_id = int(form["property_id"])
        wo.tenant_id = int(form["tenant_id"]) if form.get("tenant_id") else None
        wo.vendor_id = int(form["vendor_id"]) if form.get("vendor_id") else None
        wo.title = form["title"]
        wo.description = form.get("description", "")
        wo.category = WorkOrderCategory(form.get("category", "general"))
        wo.priority = WorkOrderPriority(form.get("priority", "normal"))
        wo.unit_area = form.get("unit_area", "")
        wo.scheduled_date = datetime.strptime(form["scheduled_date"], "%Y-%m-%d").date() if form.get("scheduled_date") else None
        wo.estimated_cost = float(form["estimated_cost"]) if form.get("estimated_cost") else None
        wo.actual_cost = float(form["actual_cost"]) if form.get("actual_cost") else None
        wo.resolution_notes = form.get("resolution_notes", "")

        if form.get("status"):
            new_status = WorkOrderStatus(form["status"])
            wo.status = new_status
            if new_status == WorkOrderStatus.COMPLETED and not wo.completed_date:
                wo.completed_date = date.today()

        wo.updated_at = datetime.utcnow()

    return RedirectResponse(url=f"/maintenance/{wo_id}", status_code=303)


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
