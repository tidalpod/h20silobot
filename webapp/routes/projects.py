"""PM-side Project (Rehab) tracking routes"""

import logging
import os
import uuid
from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Project, ProjectStatus, Property, Vendor, WorkOrder, WorkOrderStatus,
    Invoice, InvoiceStatus, ProjectDocument, SMSMessage, MessageDirection,
)
from webapp.auth.dependencies import get_current_user
from webapp.services.twilio_service import twilio_service

router = APIRouter(tags=["projects"])

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Upload directory for project documents
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_BASE) / "projects"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


def _normalize_phone(phone):
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


async def _notify_vendor_project_sms(vendor_id: int, project, session):
    """Send SMS to vendor about a project assignment"""
    try:
        result = await session.execute(
            select(Vendor).where(Vendor.id == vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if not vendor or not vendor.phone:
            return False

        # Query property for address
        prop_addr = ""
        if project.property_id:
            prop_result = await session.execute(
                select(Property).where(Property.id == project.property_id)
            )
            prop = prop_result.scalar_one_or_none()
            prop_addr = prop.address if prop else ""

        status_label = project.status.replace('_', ' ').title() if project.status else "Planning"
        budget_str = f"${project.budget:,.2f}" if project.budget else "TBD"
        start = project.start_date.strftime('%b %d, %Y') if project.start_date else "TBD"
        end = project.end_date.strftime('%b %d, %Y') if project.end_date else "TBD"

        msg = (
            f"Blue Deer - Project Assignment\n\n"
            f"Project: {project.name}\n"
            f"Property: {prop_addr}\n"
            f"Status: {status_label}\n"
            f"Budget: {budget_str}\n"
            f"Dates: {start} - {end}\n"
        )
        if project.description:
            desc_short = project.description[:100] + ("..." if len(project.description) > 100 else "")
            msg += f"Details: {desc_short}\n"

        sms_result = await twilio_service.send_sms(vendor.phone, msg)
        if sms_result.success:
            logger.info(f"Vendor SMS sent to {vendor.name} for project #{project.id}")
        else:
            logger.error(f"Failed to SMS vendor {vendor.name}: {sms_result.error_message}")

        # Store outbound message in DB for conversation tracking
        try:
            from_number = _normalize_phone(twilio_service.from_number) if twilio_service.from_number else "unknown"
            to_number = _normalize_phone(vendor.phone)
            sms_message = SMSMessage(
                vendor_id=vendor_id,
                from_number=from_number,
                to_number=to_number,
                body=msg,
                direction=MessageDirection.OUTBOUND,
                twilio_sid=sms_result.message_sid if sms_result.success else None,
                status="sent" if sms_result.success else "failed",
                created_at=datetime.utcnow()
            )
            session.add(sms_message)
            await session.flush()
        except Exception as db_err:
            logger.error(f"Failed to store vendor SMS in DB: {db_err}")

        return sms_result.success
    except Exception as e:
        logger.error(f"Error sending vendor project SMS: {e}")
        return False


@router.get("/", response_class=HTMLResponse)
async def project_list(request: Request):
    """List all projects"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Project)
            .options(
                selectinload(Project.property_ref),
                selectinload(Project.vendor_ref),
                selectinload(Project.invoices),
                selectinload(Project.work_orders),
            )
            .order_by(desc(Project.created_at))
        )
        projects = result.scalars().all()

    return templates.TemplateResponse("projects/list.html", {
        "request": request,
        "user": user,
        "projects": projects,
    })


@router.get("/new", response_class=HTMLResponse)
async def project_form(request: Request):
    """New project form"""
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

    return templates.TemplateResponse("projects/form.html", {
        "request": request,
        "user": user,
        "vendors": vendors,
        "properties": properties,
        "project": None,
        "ProjectStatus": ProjectStatus,
    })


@router.post("/new")
async def project_create(request: Request):
    """Create a new project"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    start_date = None
    end_date = None
    if form.get("start_date"):
        start_date = datetime.strptime(form["start_date"], "%Y-%m-%d").date()
    if form.get("end_date"):
        end_date = datetime.strptime(form["end_date"], "%Y-%m-%d").date()

    async with get_session() as session:
        project = Project(
            property_id=int(form["property_id"]),
            vendor_id=int(form["vendor_id"]) if form.get("vendor_id") else None,
            name=form["name"],
            description=form.get("description", ""),
            status=form.get("status", "planning"),
            budget=float(form["budget"]) if form.get("budget") else None,
            start_date=start_date,
            end_date=end_date,
        )
        session.add(project)
        await session.flush()
        project_id = project.id

        # Auto-create a work order for the vendor if assigned
        if project.vendor_id:
            wo = WorkOrder(
                property_id=project.property_id,
                vendor_id=project.vendor_id,
                project_id=project.id,
                title=project.name,
                description=project.description or "",
                status=WorkOrderStatus.ASSIGNED,
                scheduled_date=project.start_date,
                estimated_cost=project.budget,
            )
            session.add(wo)
            await session.flush()

        # Send SMS to vendor if assigned and checkbox checked
        if project.vendor_id and form.get("notify_vendor"):
            await _notify_vendor_project_sms(project.vendor_id, project, session)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: int):
    """Project detail with linked work orders and invoices"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(
                selectinload(Project.property_ref),
                selectinload(Project.vendor_ref),
                selectinload(Project.invoices).selectinload(Invoice.vendor_ref),
                selectinload(Project.work_orders).selectinload(WorkOrder.vendor_ref),
                selectinload(Project.documents),
            )
        )
        project = result.scalar_one_or_none()
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        # Get unlinked work orders for this property (for linking)
        unlinked_result = await session.execute(
            select(WorkOrder)
            .where(
                WorkOrder.property_id == project.property_id,
                WorkOrder.project_id == None,
            )
            .order_by(desc(WorkOrder.created_at))
        )
        unlinked_work_orders = unlinked_result.scalars().all()

    # Calculate budget stats
    total_spent = sum(
        float(inv.amount) for inv in project.invoices
        if inv.status in (InvoiceStatus.APPROVED.value, InvoiceStatus.PAID.value)
    )
    total_paid = sum(
        float(inv.amount) for inv in project.invoices
        if inv.status == InvoiceStatus.PAID.value
    )

    return templates.TemplateResponse("projects/detail.html", {
        "request": request,
        "user": user,
        "project": project,
        "total_spent": total_spent,
        "total_paid": total_paid,
        "unlinked_work_orders": unlinked_work_orders,
    })


@router.get("/{project_id}/edit", response_class=HTMLResponse)
async def project_edit_form(request: Request, project_id: int):
    """Edit project form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

    return templates.TemplateResponse("projects/form.html", {
        "request": request,
        "user": user,
        "vendors": vendors,
        "properties": properties,
        "project": project,
        "ProjectStatus": ProjectStatus,
    })


@router.post("/{project_id}/edit")
async def project_update(request: Request, project_id: int):
    """Update project"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            return RedirectResponse(url="/projects", status_code=303)

        old_vendor_id = project.vendor_id
        new_vendor_id = int(form["vendor_id"]) if form.get("vendor_id") else None

        project.name = form["name"]
        project.property_id = int(form["property_id"])
        project.vendor_id = new_vendor_id
        project.description = form.get("description", "")
        project.status = form.get("status", "planning")
        project.budget = float(form["budget"]) if form.get("budget") else None

        if form.get("start_date"):
            project.start_date = datetime.strptime(form["start_date"], "%Y-%m-%d").date()
        else:
            project.start_date = None

        if form.get("end_date"):
            project.end_date = datetime.strptime(form["end_date"], "%Y-%m-%d").date()
        else:
            project.end_date = None

        if project.status == ProjectStatus.COMPLETED.value and not project.completed_date:
            project.completed_date = date.today()

        # Auto-create a work order if vendor was just assigned (new or changed)
        if new_vendor_id and new_vendor_id != old_vendor_id:
            # Check if project already has a work order for this vendor
            existing_wo = await session.execute(
                select(WorkOrder).where(
                    WorkOrder.project_id == project_id,
                    WorkOrder.vendor_id == new_vendor_id,
                )
            )
            if not existing_wo.scalar_one_or_none():
                wo = WorkOrder(
                    property_id=project.property_id,
                    vendor_id=new_vendor_id,
                    project_id=project_id,
                    title=project.name,
                    description=project.description or "",
                    status=WorkOrderStatus.ASSIGNED,
                    scheduled_date=project.start_date,
                    estimated_cost=project.budget,
                )
                session.add(wo)
                await session.flush()

        # Send SMS to vendor if assigned and checkbox checked
        if project.vendor_id and form.get("notify_vendor"):
            await _notify_vendor_project_sms(project.vendor_id, project, session)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/{project_id}/add-work-order")
async def project_add_work_order(request: Request, project_id: int):
    """Link an existing work order to this project"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    wo_id = form.get("work_order_id")

    if wo_id:
        async with get_session() as session:
            result = await session.execute(
                select(WorkOrder).where(WorkOrder.id == int(wo_id))
            )
            wo = result.scalar_one_or_none()
            if wo:
                wo.project_id = project_id

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/{project_id}/delete")
async def project_delete(request: Request, project_id: int):
    """Delete a project"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project:
            await session.delete(project)

    return RedirectResponse(url="/projects", status_code=303)


@router.post("/{project_id}/create-work-order")
async def project_create_work_order(request: Request, project_id: int):
    """Create a work order from this project and assign to vendor"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project or not project.vendor_id:
            return RedirectResponse(url=f"/projects/{project_id}", status_code=303)

        wo = WorkOrder(
            property_id=project.property_id,
            vendor_id=project.vendor_id,
            project_id=project.id,
            title=project.name,
            description=project.description or "",
            status=WorkOrderStatus.ASSIGNED,
            scheduled_date=project.start_date,
            estimated_cost=project.budget,
        )
        session.add(wo)
        await session.flush()

        # Also notify vendor via SMS
        await _notify_vendor_project_sms(project.vendor_id, project, session)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/{project_id}/documents/upload")
async def project_document_upload(request: Request, project_id: int):
    """Upload a document to a project"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    file: UploadFile = form.get("file")
    title = form.get("title", "").strip() or None

    if not file or not file.filename:
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)

    if file.content_type not in ALLOWED_TYPES:
        return RedirectResponse(url=f"/projects/{project_id}?error=invalid_type", status_code=303)

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        return RedirectResponse(url=f"/projects/{project_id}?error=too_large", status_code=303)

    ext = ALLOWED_TYPES.get(file.content_type, ".pdf")
    filename = f"proj_{project_id}_{uuid.uuid4().hex[:12]}{ext}"
    filepath = UPLOAD_DIR / filename

    with open(filepath, "wb") as f:
        f.write(contents)

    file_url = f"/uploads/projects/{filename}"

    async with get_session() as session:
        doc = ProjectDocument(
            project_id=project_id,
            file_url=file_url,
            original_filename=file.filename or filename,
            file_type=ext.lstrip("."),
            file_size=len(contents),
            title=title,
        )
        session.add(doc)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)


@router.post("/{project_id}/documents/{doc_id}/delete")
async def project_document_delete(request: Request, project_id: int, doc_id: int):
    """Delete a project document"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(ProjectDocument).where(
                ProjectDocument.id == doc_id,
                ProjectDocument.project_id == project_id,
            )
        )
        doc = result.scalar_one_or_none()
        if doc:
            # Delete file from disk
            relative_path = doc.file_url.lstrip("/uploads/")
            filepath = Path(UPLOAD_BASE) / relative_path
            if filepath.exists():
                filepath.unlink()
            await session.delete(doc)

    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
