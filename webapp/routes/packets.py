"""MSHDA Landlord Packet routes — generate, list, download, entity doc management."""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    LandlordPacket, EntityDocument, EntityConfig,
    Property, Tenant, EntityBankAccount,
)
from webapp.auth.dependencies import get_current_user
from webapp.services.storage_service import storage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["packets"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# =============================================================================
# Packet List
# =============================================================================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def packet_list(request: Request):
    """List all generated MSHDA landlord packets."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Load packets with relations
        result = await session.execute(
            select(LandlordPacket)
            .options(
                selectinload(LandlordPacket.property),
                selectinload(LandlordPacket.tenant),
                selectinload(LandlordPacket.entity),
            )
            .order_by(desc(LandlordPacket.generated_at))
        )
        packets = result.scalars().all()

        # Load entities with their documents for the doc management section
        ent_result = await session.execute(
            select(EntityConfig)
            .options(selectinload(EntityConfig.documents))
            .order_by(EntityConfig.entity_name)
        )
        entities = ent_result.scalars().all()

    return templates.TemplateResponse(
        "packets/list.html",
        {"request": request, "user": user, "packets": packets, "entities": entities},
    )


# =============================================================================
# Generate Form
# =============================================================================

@router.get("/generate", response_class=HTMLResponse)
async def generate_form(request: Request):
    """Display the packet generation form."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Properties
        prop_result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .order_by(Property.address)
        )
        properties = prop_result.scalars().all()

        # Tenants (active)
        tenant_result = await session.execute(
            select(Tenant)
            .options(selectinload(Tenant.property_ref))
            .where(Tenant.is_active == True)
            .order_by(Tenant.name)
        )
        tenants = tenant_result.scalars().all()

        # Entities with doc status
        ent_result = await session.execute(
            select(EntityConfig)
            .options(
                selectinload(EntityConfig.documents),
                selectinload(EntityConfig.bank_accounts),
            )
            .order_by(EntityConfig.entity_name)
        )
        entities = ent_result.scalars().all()

    return templates.TemplateResponse(
        "packets/generate.html",
        {
            "request": request,
            "user": user,
            "properties": properties,
            "tenants": tenants,
            "entities": entities,
        },
    )


# =============================================================================
# API: Property / Tenant / Entity data for JS auto-fill
# =============================================================================

@router.get("/api/property/{property_id}")
async def api_property_data(request: Request, property_id: int):
    """Return property data as JSON for form auto-fill."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if not prop:
            return JSONResponse({"error": "not found"}, status_code=404)

        return JSONResponse({
            "address": prop.address or "",
            "city": prop.city or "",
            "state": prop.state or "",
            "zip_code": prop.zip_code or "",
            "bedrooms": prop.bedrooms,
            "bathrooms": str(prop.bathrooms) if prop.bathrooms else "",
            "year_built": prop.year_built,
            "property_type": prop.property_type or "",
            "entity": prop.entity or "",
            "monthly_rent": str(prop.monthly_rent) if prop.monthly_rent else "",
            "lease_start_date": str(prop.lease_start_date) if prop.lease_start_date else "",
            "lease_end_date": str(prop.lease_end_date) if prop.lease_end_date else "",
        })


@router.get("/api/tenant/{tenant_id}")
async def api_tenant_data(request: Request, tenant_id: int):
    """Return tenant data as JSON for form auto-fill."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async with get_session() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()
        if not tenant:
            return JSONResponse({"error": "not found"}, status_code=404)

        return JSONResponse({
            "name": tenant.name or "",
            "phone": tenant.phone or "",
            "email": tenant.email or "",
            "is_section8": tenant.is_section8,
            "current_rent": str(tenant.current_rent) if tenant.current_rent else "",
            "proposed_rent": str(tenant.proposed_rent) if tenant.proposed_rent else "",
            "voucher_amount": str(tenant.voucher_amount) if tenant.voucher_amount else "",
            "tenant_portion": str(tenant.tenant_portion) if tenant.tenant_portion else "",
            "lease_start_date": str(tenant.lease_start_date) if tenant.lease_start_date else "",
            "lease_end_date": str(tenant.lease_end_date) if tenant.lease_end_date else "",
            "property_id": tenant.property_id,
        })


@router.get("/api/entity/{entity_id}")
async def api_entity_data(request: Request, entity_id: int):
    """Return entity data as JSON for form auto-fill."""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    async with get_session() as session:
        result = await session.execute(
            select(EntityConfig)
            .options(
                selectinload(EntityConfig.documents),
                selectinload(EntityConfig.bank_accounts),
            )
            .where(EntityConfig.id == entity_id)
        )
        entity = result.scalar_one_or_none()
        if not entity:
            return JSONResponse({"error": "not found"}, status_code=404)

        # Check for uploaded docs
        has_w9 = any(d.doc_type == "w9" for d in entity.documents)
        has_payee = any(d.doc_type == "payee_auth" for d in entity.documents)

        # Get default bank account info
        default_bank = next(
            (b for b in entity.bank_accounts if b.is_default and b.is_active),
            next((b for b in entity.bank_accounts if b.is_active), None),
        )

        return JSONResponse({
            "entity_name": entity.entity_name or "",
            "owner_name": entity.owner_name or "",
            "email": entity.email or "",
            "phone": entity.phone or "",
            "ein": getattr(entity, 'ein', '') or "",
            "mailing_address": getattr(entity, 'full_address', '') or entity.mailing_address or "",
            "has_w9": has_w9,
            "has_payee_auth": has_payee,
            "bank_name": default_bank.institution_name if default_bank else "",
            "bank_routing_number": default_bank.routing_number if default_bank else "",
            "bank_account_number": (
                f"****{default_bank.account_mask}" if default_bank and default_bank.account_mask else ""
            ),
        })


# =============================================================================
# Generate Packet (POST)
# =============================================================================

@router.post("/generate")
async def generate_packet_post(request: Request):
    """Process the generation form, create PDF, store, redirect."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    form_data = {k: v for k, v in form.items() if isinstance(v, str)}

    property_id = int(form_data.get("property_id", 0))
    tenant_id = int(form_data.get("tenant_id", 0)) if form_data.get("tenant_id") else None
    entity_id = int(form_data.get("entity_id", 0)) if form_data.get("entity_id") else None

    if not property_id:
        return RedirectResponse(url="/packets/generate?error=property_required", status_code=303)

    # Look up entity documents
    entity_w9_path = None
    entity_payee_path = None

    async with get_session() as session:
        if entity_id:
            doc_result = await session.execute(
                select(EntityDocument).where(EntityDocument.entity_id == entity_id)
            )
            docs = doc_result.scalars().all()
            for doc in docs:
                if doc.doc_type == "w9":
                    entity_w9_path = _resolve_file_path(doc.file_url)
                elif doc.doc_type == "payee_auth":
                    entity_payee_path = _resolve_file_path(doc.file_url)

    # Generate the PDF
    try:
        from webapp.services.packet_generator import generate_packet as gen_pdf
        pdf_bytes = gen_pdf(
            form_data=form_data,
            entity_w9_path=entity_w9_path,
            entity_payee_path=entity_payee_path,
        )
    except FileNotFoundError as e:
        logger.error(f"Packet generation failed: {e}")
        return RedirectResponse(
            url="/packets/generate?error=blank_pdf_missing",
            status_code=303,
        )
    except Exception as e:
        logger.error(f"Packet generation failed: {e}", exc_info=True)
        return RedirectResponse(
            url="/packets/generate?error=generation_failed",
            status_code=303,
        )

    # Store the generated PDF
    filename = f"packets/mshda_packet_{uuid.uuid4().hex[:8]}.pdf"
    file_url = storage.upload(filename, pdf_bytes, content_type="application/pdf")

    # Save record
    async with get_session() as session:
        packet = LandlordPacket(
            property_id=property_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            file_url=file_url,
            form_data=json.dumps(form_data),
        )
        session.add(packet)

    return RedirectResponse(url="/packets?success=generated", status_code=303)


# =============================================================================
# Download
# =============================================================================

@router.get("/{packet_id}/download")
async def download_packet(request: Request, packet_id: int):
    """Download a generated packet PDF."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LandlordPacket)
            .options(selectinload(LandlordPacket.property))
            .where(LandlordPacket.id == packet_id)
        )
        packet = result.scalar_one_or_none()
        if not packet or not packet.file_url:
            return RedirectResponse(url="/packets?error=not_found", status_code=303)

        # Download file bytes
        pdf_bytes = storage.download(packet.file_url)
        if not pdf_bytes:
            # Try direct URL redirect for R2 files
            if packet.file_url.startswith("http"):
                return RedirectResponse(url=packet.file_url)
            return RedirectResponse(url="/packets?error=file_missing", status_code=303)

        addr = packet.property.address if packet.property else "packet"
        safe_addr = "".join(c if c.isalnum() or c in " -_" else "" for c in addr).strip()
        filename = f"MSHDA_Packet_{safe_addr}.pdf"

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


# =============================================================================
# Delete Packet
# =============================================================================

@router.post("/{packet_id}/delete")
async def delete_packet(request: Request, packet_id: int):
    """Delete a generated packet."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LandlordPacket).where(LandlordPacket.id == packet_id)
        )
        packet = result.scalar_one_or_none()
        if packet:
            if packet.file_url:
                storage.delete(packet.file_url)
            await session.delete(packet)

    return RedirectResponse(url="/packets?success=deleted", status_code=303)


# =============================================================================
# Entity Document Upload / Delete
# =============================================================================

@router.post("/entities/{entity_id}/documents/upload")
async def upload_entity_document(
    request: Request,
    entity_id: int,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload a W-9 or Payee Auth PDF for an entity."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if doc_type not in ("w9", "payee_auth"):
        return RedirectResponse(url="/packets?error=invalid_doc_type", status_code=303)

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return RedirectResponse(url="/packets?error=pdf_only", status_code=303)

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:  # 10MB limit
        return RedirectResponse(url="/packets?error=file_too_large", status_code=303)

    # Upload to storage
    key = f"entity_docs/{entity_id}/{doc_type}_{uuid.uuid4().hex[:8]}.pdf"
    file_url = storage.upload(key, contents, content_type="application/pdf")

    async with get_session() as session:
        # Remove old doc of same type for this entity
        old_result = await session.execute(
            select(EntityDocument)
            .where(EntityDocument.entity_id == entity_id)
            .where(EntityDocument.doc_type == doc_type)
        )
        for old_doc in old_result.scalars().all():
            storage.delete(old_doc.file_url)
            await session.delete(old_doc)

        # Create new doc record
        doc = EntityDocument(
            entity_id=entity_id,
            doc_type=doc_type,
            file_url=file_url,
            original_filename=file.filename,
        )
        session.add(doc)

    return RedirectResponse(url="/packets?success=uploaded", status_code=303)


@router.post("/entities/{entity_id}/documents/{doc_id}/delete")
async def delete_entity_document(
    request: Request,
    entity_id: int,
    doc_id: int,
):
    """Delete an entity document."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(EntityDocument)
            .where(EntityDocument.id == doc_id)
            .where(EntityDocument.entity_id == entity_id)
        )
        doc = result.scalar_one_or_none()
        if doc:
            storage.delete(doc.file_url)
            await session.delete(doc)

    return RedirectResponse(url="/packets?success=doc_deleted", status_code=303)


# =============================================================================
# Helpers
# =============================================================================

def _resolve_file_path(file_url: str) -> str:
    """Convert a file URL to something the packet generator can read.

    R2 URLs are returned as-is (https://...).
    Local /uploads/... paths are converted to absolute filesystem paths.
    """
    if file_url.startswith(("http://", "https://")):
        return file_url

    if file_url.startswith("/uploads/"):
        from webapp.main import UPLOAD_DIR
        return str(UPLOAD_DIR / file_url.removeprefix("/uploads/"))

    return file_url
