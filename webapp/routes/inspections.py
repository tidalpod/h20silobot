"""Inspections routes"""

import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Property, Tenant, SMSMessage, MessageDirection,
    Vendor, COInspectionDocument, COInspectionVendor,
)
from webapp.auth.dependencies import get_current_user
from webapp.services.storage_service import storage
from webapp.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/inspections", tags=["inspections"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string to date object"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


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


async def _notify_tenants_inspection_sms(property_id: int, inspection_type: str, date: str, time: str, session):
    """Send SMS to all active tenants at a property about an inspection."""
    try:
        # Load tenants separately to avoid identity map caching issues
        tenant_result = await session.execute(
            select(Tenant).where(
                Tenant.property_id == property_id,
                Tenant.is_active == True
            )
        )
        tenants = tenant_result.scalars().all()

        prop_result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = prop_result.scalar_one_or_none()
        if not prop:
            logger.warning(f"Inspection notify: property {property_id} not found")
            return

        logger.info(f"Inspection notify: property={prop.address}, type={inspection_type}, tenants found={len(tenants)}")

        parsed_date = parse_date(date)
        date_str = parsed_date.strftime('%b %d, %Y') if parsed_date else "TBD"
        time_str = time if time else "TBD"

        for tenant in tenants:
            if not tenant.phone:
                logger.info(f"Skipping tenant {tenant.name} - no phone number")
                continue

            phone = _normalize_phone(tenant.phone)
            if not phone:
                continue

            if inspection_type == "section8":
                msg = (
                    f"Blue Deer Property Management\n\n"
                    f"Your Section 8 inspection has been scheduled:\n\n"
                    f"Property: {prop.address}\n"
                    f"Date: {date_str}\n"
                    f"Time: {time_str}\n\n"
                    f"Please ensure the unit is accessible and all areas are reachable. Reply with any questions."
                )
            else:
                msg = (
                    f"Blue Deer Property Management\n\n"
                    f"Your rental inspection has been scheduled:\n\n"
                    f"Property: {prop.address}\n"
                    f"Date: {date_str}\n"
                    f"Time: {time_str}\n\n"
                    f"Please ensure the unit is accessible. Reply with any questions."
                )

            sms_result = await twilio_service.send_sms(phone, msg)

            try:
                from_number = _normalize_phone(twilio_service.from_number) if twilio_service.from_number else "unknown"
                sms_message = SMSMessage(
                    tenant_id=tenant.id,
                    property_id=property_id,
                    from_number=from_number,
                    to_number=phone,
                    body=msg,
                    direction=MessageDirection.OUTBOUND,
                    twilio_sid=sms_result.message_sid if sms_result.success else None,
                    status="sent" if sms_result.success else "failed",
                    created_at=datetime.utcnow()
                )
                session.add(sms_message)
                await session.flush()
            except Exception as db_err:
                logger.error(f"Failed to store inspection SMS in DB: {db_err}")

            if sms_result.success:
                logger.info(f"Inspection SMS sent to tenant {tenant.name} at {phone}")
            else:
                logger.warning(f"Failed to send inspection SMS to tenant {tenant.name}: {sms_result.error}")

    except Exception as e:
        logger.error(f"Error sending inspection SMS notifications: {e}")


@router.get("/", response_class=HTMLResponse)
async def inspections_list(request: Request):
    """List all upcoming inspections"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    today = datetime.now().date()

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        # Collect all inspections
        co_inspections = []
        rental_inspections = []
        section8_inspections = []

        for prop in properties:
            # CO Inspections
            co_types = [
                ("Mechanical", "co_mechanical_date", "co_mechanical_time", "⚙️"),
                ("Electrical", "co_electrical_date", "co_electrical_time", "⚡"),
                ("Plumbing", "co_plumbing_date", "co_plumbing_time", "🔧"),
                ("Zoning", "co_zoning_date", "co_zoning_time", "📐"),
                ("Building", "co_building_date", "co_building_time", "🏢"),
            ]

            for insp_name, date_field, time_field, icon in co_types:
                insp_date = getattr(prop, date_field)
                insp_time = getattr(prop, time_field)
                if insp_date:
                    days_until = (insp_date - today).days
                    co_inspections.append({
                        "property": prop,
                        "type": insp_name,
                        "icon": icon,
                        "date": insp_date,
                        "time": insp_time,
                        "days_until": days_until,
                        "is_past": days_until < 0
                    })

            # Rental Inspection
            if prop.rental_inspection_date:
                days_until = (prop.rental_inspection_date - today).days
                rental_inspections.append({
                    "property": prop,
                    "date": prop.rental_inspection_date,
                    "time": prop.rental_inspection_time,
                    "days_until": days_until,
                    "is_past": days_until < 0
                })

            # Section 8 Inspection
            if prop.section8_inspection_date and prop.section8_inspection_status in ('scheduled', 'pending', 'reinspection'):
                days_until = (prop.section8_inspection_date - today).days
                section8_inspections.append({
                    "property": prop,
                    "status": prop.section8_inspection_status,
                    "date": prop.section8_inspection_date,
                    "time": prop.section8_inspection_time,
                    "notes": prop.section8_inspection_notes,
                    "days_until": days_until,
                    "is_past": days_until < 0
                })

        # Sort by date
        co_inspections.sort(key=lambda x: x["date"])
        rental_inspections.sort(key=lambda x: x["date"])
        section8_inspections.sort(key=lambda x: x["date"])

        # Separate upcoming and past
        upcoming_co = [i for i in co_inspections if not i["is_past"]]
        past_co = [i for i in co_inspections if i["is_past"]]

        upcoming_rental = [i for i in rental_inspections if not i["is_past"]]
        past_rental = [i for i in rental_inspections if i["is_past"]]

        upcoming_section8 = [i for i in section8_inspections if not i["is_past"]]
        past_section8 = [i for i in section8_inspections if i["is_past"]]

    return templates.TemplateResponse(
        "inspections/list.html",
        {
            "request": request,
            "user": user,
            "today": today,
            # All properties for scheduling new inspections
            "properties": properties,
            # CO Inspections
            "upcoming_co": upcoming_co,
            "past_co": past_co[:10],  # Last 10 past
            # Rental Inspections
            "upcoming_rental": upcoming_rental,
            "past_rental": past_rental[:10],
            # Section 8 Inspections
            "upcoming_section8": upcoming_section8,
            "past_section8": past_section8[:10],
            # Counts
            "total_upcoming": len(upcoming_co) + len(upcoming_rental) + len(upcoming_section8),
        }
    )


@router.post("/co/update")
async def update_co_inspection(
    request: Request,
    property_id: int = Form(...),
    inspection_type: str = Form(...),
    date: str = Form(""),
    time: str = Form(""),
    status: str = Form(""),
    redirect: str = Form(""),
):
    """Update a CO inspection date/time/status"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Map inspection type to field names
    field_map = {
        "mechanical": ("co_mechanical_date", "co_mechanical_time", "co_mechanical_status"),
        "electrical": ("co_electrical_date", "co_electrical_time", "co_electrical_status"),
        "plumbing": ("co_plumbing_date", "co_plumbing_time", "co_plumbing_status"),
        "zoning": ("co_zoning_date", "co_zoning_time", "co_zoning_status"),
        "building": ("co_building_date", "co_building_time", "co_building_status"),
    }

    if inspection_type.lower() not in field_map:
        return RedirectResponse(url="/inspections", status_code=303)

    date_field, time_field, status_field = field_map[inspection_type.lower()]

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            setattr(prop, date_field, parse_date(date))
            setattr(prop, time_field, time if time else None)
            setattr(prop, status_field, status if status in ("passed", "failed") else None)
            await session.commit()

    if redirect:
        return RedirectResponse(url=redirect, status_code=303)
    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/rental/update")
async def update_rental_inspection(
    request: Request,
    property_id: int = Form(...),
    date: str = Form(""),
    time: str = Form(""),
    notify_tenant: str = Form("")
):
    """Update a rental inspection date/time"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            prop.rental_inspection_date = parse_date(date)
            prop.rental_inspection_time = time if time else None
            await session.commit()

            if notify_tenant and date:
                await _notify_tenants_inspection_sms(property_id, "rental", date, time, session)
                await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/section8/update")
async def update_section8_inspection(
    request: Request,
    property_id: int = Form(...),
    date: str = Form(""),
    time: str = Form(""),
    status: str = Form("scheduled"),
    notes: str = Form(""),
    notify_tenant: str = Form("")
):
    """Update a Section 8 inspection"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            prop.section8_inspection_date = parse_date(date)
            prop.section8_inspection_time = time if time else None
            prop.section8_inspection_status = status if status else None
            prop.section8_inspection_notes = notes if notes else None
            await session.commit()

            if notify_tenant and date:
                await _notify_tenants_inspection_sms(property_id, "section8", date, time, session)
                await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/notify")
async def notify_inspection(
    request: Request,
    property_id: int = Form(...),
    inspection_type: str = Form(...),
):
    """Send SMS notification to tenants about an existing inspection"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            if inspection_type == "rental" and prop.rental_inspection_date:
                date_str = prop.rental_inspection_date.strftime("%Y-%m-%d")
                time_str = prop.rental_inspection_time or ""
                await _notify_tenants_inspection_sms(property_id, "rental", date_str, time_str, session)
                await session.commit()
            elif inspection_type == "section8" and prop.section8_inspection_date:
                date_str = prop.section8_inspection_date.strftime("%Y-%m-%d")
                time_str = prop.section8_inspection_time or ""
                await _notify_tenants_inspection_sms(property_id, "section8", date_str, time_str, session)
                await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/delete")
async def delete_inspection(
    request: Request,
    property_id: int = Form(...),
    inspection_category: str = Form(...),
    inspection_type: str = Form("")
):
    """Clear an inspection date (delete)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            if inspection_category == "co":
                field_map = {
                    "mechanical": ("co_mechanical_date", "co_mechanical_time"),
                    "electrical": ("co_electrical_date", "co_electrical_time"),
                    "plumbing": ("co_plumbing_date", "co_plumbing_time"),
                    "zoning": ("co_zoning_date", "co_zoning_time"),
                    "building": ("co_building_date", "co_building_time"),
                }
                if inspection_type.lower() in field_map:
                    date_field, time_field = field_map[inspection_type.lower()]
                    setattr(prop, date_field, None)
                    setattr(prop, time_field, None)
            elif inspection_category == "rental":
                prop.rental_inspection_date = None
                prop.rental_inspection_time = None
            elif inspection_category == "section8":
                prop.section8_inspection_date = None
                prop.section8_inspection_time = None
                prop.section8_inspection_status = None
                prop.section8_inspection_notes = None
            await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


# =============================================================================
# CO Inspection Profile
# =============================================================================

CO_TYPES = ["building", "zoning", "electrical", "mechanical", "plumbing"]
CO_TYPE_META = {
    "building": {"label": "Building", "icon": "🏢"},
    "zoning": {"label": "Zoning", "icon": "📐"},
    "electrical": {"label": "Electrical", "icon": "⚡"},
    "mechanical": {"label": "Mechanical", "icon": "⚙️"},
    "plumbing": {"label": "Plumbing", "icon": "🔧"},
}


@router.get("/co/property/{property_id}", response_class=HTMLResponse)
async def co_profile(request: Request, property_id: int):
    """CO inspection profile page for a property"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # Load CO documents grouped by type
        docs_result = await session.execute(
            select(COInspectionDocument)
            .where(COInspectionDocument.property_id == property_id)
            .order_by(COInspectionDocument.uploaded_at.desc())
        )
        all_docs = docs_result.scalars().all()
        co_docs_by_type = {}
        for t in CO_TYPES:
            co_docs_by_type[t] = [d for d in all_docs if d.inspection_type == t]

        # Load CO vendor assignments keyed by type
        vendors_result = await session.execute(
            select(COInspectionVendor)
            .where(COInspectionVendor.property_id == property_id)
            .options(selectinload(COInspectionVendor.vendor))
        )
        all_vendor_assignments = vendors_result.scalars().all()
        co_vendors_by_type = {va.inspection_type: va for va in all_vendor_assignments}

        # Load all active vendors for dropdown
        vendor_list_result = await session.execute(
            select(Vendor)
            .where(Vendor.is_active == True)
            .order_by(Vendor.name)
        )
        vendors = vendor_list_result.scalars().all()

    return templates.TemplateResponse(
        "inspections/co_profile.html",
        {
            "request": request,
            "user": user,
            "property": prop,
            "co_types": CO_TYPES,
            "co_type_meta": CO_TYPE_META,
            "co_docs_by_type": co_docs_by_type,
            "co_vendors_by_type": co_vendors_by_type,
            "vendors": vendors,
        }
    )


@router.post("/co/property/{property_id}/vendor/assign")
async def assign_co_vendor(
    request: Request,
    property_id: int,
    inspection_type: str = Form(...),
    vendor_id: int = Form(...),
    notes: str = Form(""),
):
    """Assign a vendor to a CO inspection type (or all types)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    types_to_assign = CO_TYPES if inspection_type == "all" else [inspection_type]

    async with get_session() as session:
        for t in types_to_assign:
            if t not in CO_TYPES:
                continue
            result = await session.execute(
                select(COInspectionVendor).where(
                    COInspectionVendor.property_id == property_id,
                    COInspectionVendor.inspection_type == t,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.vendor_id = vendor_id
                existing.notes = notes or None
                existing.assigned_at = datetime.utcnow()
            else:
                session.add(COInspectionVendor(
                    property_id=property_id,
                    inspection_type=t,
                    vendor_id=vendor_id,
                    notes=notes or None,
                ))
        await session.commit()

    return RedirectResponse(url=f"/inspections/co/property/{property_id}", status_code=303)


@router.post("/co/property/{property_id}/docs/upload")
async def upload_co_document(
    request: Request,
    property_id: int,
    inspection_type: str = Form(...),
    description: str = Form(""),
    doc_file: UploadFile = File(None),
    doc_image: UploadFile = File(None),
):
    """Upload a document (PDF and/or image) for a CO inspection type"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if inspection_type not in CO_TYPES:
        return RedirectResponse(url=f"/inspections/co/property/{property_id}", status_code=303)

    # Handle PDF
    pdf_contents = None
    pdf_filename = None
    if doc_file and doc_file.filename:
        if doc_file.content_type == "application/pdf":
            pdf_contents = await doc_file.read()
            if len(pdf_contents) > 20 * 1024 * 1024:
                pdf_contents = None
            else:
                ext = Path(doc_file.filename).suffix.lower() or ".pdf"
                pdf_filename = f"{property_id}_{inspection_type}_{uuid.uuid4().hex[:8]}{ext}"

    # Handle image
    image_contents = None
    image_filename = None
    if doc_image and doc_image.filename:
        allowed_image_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
        if doc_image.content_type in allowed_image_types:
            image_contents = await doc_image.read()
            if len(image_contents) > 10 * 1024 * 1024:
                image_contents = None
            else:
                img_ext = Path(doc_image.filename).suffix.lower() or ".jpg"
                image_filename = f"{property_id}_{inspection_type}_{uuid.uuid4().hex[:8]}{img_ext}"

    if not pdf_contents and not image_contents:
        return RedirectResponse(url=f"/inspections/co/property/{property_id}", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        saved_pdf_url = None
        original_name = None
        if pdf_contents and pdf_filename:
            key = f"co_inspections/{pdf_filename}"
            saved_pdf_url = storage.upload(key, pdf_contents, "application/pdf")
            original_name = doc_file.filename

        saved_image_url = None
        if image_contents and image_filename:
            key = f"co_inspections/{image_filename}"
            saved_image_url = storage.upload(key, image_contents, doc_image.content_type)

        doc = COInspectionDocument(
            property_id=property_id,
            inspection_type=inspection_type,
            file_url=saved_pdf_url,
            image_url=saved_image_url,
            original_filename=original_name,
            description=description or None,
        )
        session.add(doc)
        await session.commit()

    return RedirectResponse(url=f"/inspections/co/property/{property_id}", status_code=303)


@router.post("/co/property/{property_id}/docs/{doc_id}/delete")
async def delete_co_document(request: Request, property_id: int, doc_id: int):
    """Delete a CO inspection document"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(COInspectionDocument)
            .where(COInspectionDocument.id == doc_id)
            .where(COInspectionDocument.property_id == property_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        if doc.file_url:
            storage.delete(doc.file_url)
        if doc.image_url:
            storage.delete(doc.image_url)

        await session.delete(doc)
        await session.commit()

    return RedirectResponse(url=f"/inspections/co/property/{property_id}", status_code=303)
