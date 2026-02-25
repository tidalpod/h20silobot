"""Lease management routes"""

import os
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import LeaseDocument, LeaseStatus, Property, Tenant
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["leases"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Upload directory for lease documents
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_BASE) / "leases"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@router.get("/", response_class=HTMLResponse)
async def list_leases(
    request: Request,
    status: str = None,
    property_id: int = None,
    expiring: bool = False,
):
    """List lease documents"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(LeaseDocument)
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
        )

        if status:
            query = query.where(LeaseDocument.status == LeaseStatus(status))
        else:
            # Exclude terminated by default
            query = query.where(LeaseDocument.status != LeaseStatus.TERMINATED)

        if property_id:
            query = query.where(LeaseDocument.property_id == property_id)

        query = query.order_by(desc(LeaseDocument.created_at))
        result = await session.execute(query)
        leases = result.scalars().all()

        # Find expiring soon (within 30 days)
        expiring_leases = []
        today = date.today()
        threshold = today + timedelta(days=30)
        for lease in leases:
            if lease.lease_end and today <= lease.lease_end <= threshold and lease.status == LeaseStatus.ACTIVE:
                expiring_leases.append(lease)

        if expiring:
            leases = expiring_leases

        # Get properties for filter
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

    return templates.TemplateResponse(
        "leases/list.html",
        {
            "request": request,
            "user": user,
            "leases": leases,
            "properties": properties,
            "expiring_leases": expiring_leases,
            "statuses": LeaseStatus,
            "filter_status": status,
            "filter_property_id": property_id,
            "filter_expiring": expiring,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_lease_form(request: Request):
    """Upload lease form"""
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

    return templates.TemplateResponse(
        "leases/form.html",
        {
            "request": request,
            "user": user,
            "lease": None,
            "properties": properties,
            "tenants": tenants,
        }
    )


@router.post("/new")
async def create_lease(request: Request):
    """Upload and create a lease document"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    file: UploadFile = form.get("file")

    if not file or not file.filename:
        return RedirectResponse(url="/leases/new?error=no_file", status_code=303)

    if file.content_type not in ALLOWED_TYPES:
        return RedirectResponse(url="/leases/new?error=invalid_type", status_code=303)

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        return RedirectResponse(url="/leases/new?error=too_large", status_code=303)

    ext = ALLOWED_TYPES.get(file.content_type, ".pdf")
    filename = f"lease_{uuid.uuid4().hex[:12]}{ext}"
    filepath = UPLOAD_DIR / filename

    with open(filepath, "wb") as f:
        f.write(contents)

    async with get_session() as session:
        lease = LeaseDocument(
            property_id=int(form["property_id"]),
            tenant_id=int(form["tenant_id"]) if form.get("tenant_id") else None,
            title=form.get("title", file.filename),
            file_url=f"/uploads/leases/{filename}",
            file_type=ext.lstrip("."),
            file_size=len(contents),
            lease_start=datetime.strptime(form["lease_start"], "%Y-%m-%d").date() if form.get("lease_start") else None,
            lease_end=datetime.strptime(form["lease_end"], "%Y-%m-%d").date() if form.get("lease_end") else None,
            monthly_rent=float(form["monthly_rent"]) if form.get("monthly_rent") else None,
            notes=form.get("notes", ""),
            status=LeaseStatus.ACTIVE,
        )
        session.add(lease)
        await session.flush()
        lease_id = lease.id

    return RedirectResponse(url=f"/leases/{lease_id}", status_code=303)


@router.get("/{lease_id}", response_class=HTMLResponse)
async def lease_detail(request: Request, lease_id: int):
    """Lease detail with PDF viewer"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument)
            .where(LeaseDocument.id == lease_id)
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
        )
        lease = result.scalar_one_or_none()
        if not lease:
            return RedirectResponse(url="/leases", status_code=303)

    return templates.TemplateResponse(
        "leases/detail.html",
        {"request": request, "user": user, "lease": lease}
    )


@router.get("/{lease_id}/edit", response_class=HTMLResponse)
async def edit_lease_form(request: Request, lease_id: int):
    """Edit lease metadata"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument).where(LeaseDocument.id == lease_id)
        )
        lease = result.scalar_one_or_none()
        if not lease:
            return RedirectResponse(url="/leases", status_code=303)

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        tenants_result = await session.execute(
            select(Tenant).where(Tenant.is_active == True).order_by(Tenant.name)
        )
        tenants = tenants_result.scalars().all()

    return templates.TemplateResponse(
        "leases/form.html",
        {
            "request": request,
            "user": user,
            "lease": lease,
            "properties": properties,
            "tenants": tenants,
        }
    )


@router.post("/{lease_id}/edit")
async def update_lease(request: Request, lease_id: int):
    """Update lease metadata"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument).where(LeaseDocument.id == lease_id)
        )
        lease = result.scalar_one_or_none()
        if not lease:
            return RedirectResponse(url="/leases", status_code=303)

        lease.property_id = int(form["property_id"])
        lease.tenant_id = int(form["tenant_id"]) if form.get("tenant_id") else None
        lease.title = form.get("title", lease.title)
        lease.lease_start = datetime.strptime(form["lease_start"], "%Y-%m-%d").date() if form.get("lease_start") else None
        lease.lease_end = datetime.strptime(form["lease_end"], "%Y-%m-%d").date() if form.get("lease_end") else None
        lease.monthly_rent = float(form["monthly_rent"]) if form.get("monthly_rent") else None
        lease.notes = form.get("notes", "")

        if form.get("status"):
            lease.status = LeaseStatus(form["status"])

        lease.updated_at = datetime.utcnow()

    return RedirectResponse(url=f"/leases/{lease_id}", status_code=303)


@router.post("/{lease_id}/delete")
async def delete_lease(request: Request, lease_id: int):
    """Soft delete (terminate) a lease"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument).where(LeaseDocument.id == lease_id)
        )
        lease = result.scalar_one_or_none()
        if lease:
            lease.status = LeaseStatus.TERMINATED
            lease.updated_at = datetime.utcnow()

    return RedirectResponse(url="/leases", status_code=303)


@router.get("/{lease_id}/download")
async def download_lease(request: Request, lease_id: int):
    """Serve the lease file for download"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseDocument).where(LeaseDocument.id == lease_id)
        )
        lease = result.scalar_one_or_none()
        if not lease:
            return RedirectResponse(url="/leases", status_code=303)

        # Convert URL path to file path
        relative_path = lease.file_url.lstrip("/uploads/")
        filepath = Path(UPLOAD_BASE) / relative_path

        if not filepath.exists():
            return RedirectResponse(url=f"/leases/{lease_id}?error=file_missing", status_code=303)

        return FileResponse(
            path=str(filepath),
            filename=f"{lease.title}.{lease.file_type}",
            media_type="application/octet-stream",
        )
