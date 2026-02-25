"""PM-side Project (Rehab) tracking routes"""

from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Project, ProjectStatus, Property, Vendor, WorkOrder, Invoice, InvoiceStatus,
)
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["projects"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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
            status=ProjectStatus(form.get("status", "planning")),
            budget=float(form["budget"]) if form.get("budget") else None,
            start_date=start_date,
            end_date=end_date,
        )
        session.add(project)
        await session.flush()
        project_id = project.id

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
        if inv.status in (InvoiceStatus.APPROVED, InvoiceStatus.PAID)
    )
    total_paid = sum(
        float(inv.amount) for inv in project.invoices
        if inv.status == InvoiceStatus.PAID
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

        project.name = form["name"]
        project.property_id = int(form["property_id"])
        project.vendor_id = int(form["vendor_id"]) if form.get("vendor_id") else None
        project.description = form.get("description", "")
        project.status = ProjectStatus(form.get("status", "planning"))
        project.budget = float(form["budget"]) if form.get("budget") else None

        if form.get("start_date"):
            project.start_date = datetime.strptime(form["start_date"], "%Y-%m-%d").date()
        else:
            project.start_date = None

        if form.get("end_date"):
            project.end_date = datetime.strptime(form["end_date"], "%Y-%m-%d").date()
        else:
            project.end_date = None

        if project.status == ProjectStatus.COMPLETED and not project.completed_date:
            project.completed_date = date.today()

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
