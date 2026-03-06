"""Showings routes - schedule and track vendor showings"""

import logging
from datetime import datetime, date, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Showing, ShowingType, ShowingStatus,
    Vendor, Property, SMSMessage, MessageDirection,
)
from webapp.auth.dependencies import get_current_user
from webapp.services.twilio_service import twilio_service

router = APIRouter(tags=["showings"])

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


async def _notify_vendor_showing_sms(vendor_id: int, showing, session):
    """Send SMS to vendor about a showing assignment"""
    try:
        result = await session.execute(
            select(Vendor).where(Vendor.id == vendor_id)
        )
        vendor = result.scalar_one_or_none()
        if not vendor or not vendor.phone:
            return False

        prop_addr = ""
        if showing.property_id:
            prop_result = await session.execute(
                select(Property).where(Property.id == showing.property_id)
            )
            prop = prop_result.scalar_one_or_none()
            prop_addr = prop.address if prop else ""

        date_str = showing.scheduled_date.strftime('%b %d, %Y') if showing.scheduled_date else "TBD"
        time_str = showing.scheduled_time or "TBD"

        msg = (
            f"Blue Deer - New Showing Assigned\n\n"
            f"Title: {showing.title}\n"
            f"Property: {prop_addr}\n"
            f"Date: {date_str}\n"
            f"Time: {time_str}\n"
        )
        if showing.contact_name:
            msg += f"Prospective Renter: {showing.contact_name}"
            if showing.contact_phone:
                msg += f" ({showing.contact_phone})"
            msg += "\n"
        msg += f"\nView in portal: https://bluedeer.space/vendor/showings/{showing.id}"

        sms_result = await twilio_service.send_sms(vendor.phone, msg)
        if sms_result.success:
            logger.info(f"Vendor SMS sent to {vendor.name} for Showing #{showing.id}")
        else:
            logger.error(f"Failed to SMS vendor {vendor.name}: {sms_result.error_message}")

        # Store outbound message in DB
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
        logger.error(f"Error sending vendor showing SMS: {e}")
        return False


async def _notify_renter_showing_sms(showing, session):
    """Send SMS to prospective renter about a showing"""
    try:
        phone = _normalize_phone(showing.contact_phone)
        if not phone:
            return False

        prop_addr = ""
        if showing.property_id:
            prop_result = await session.execute(
                select(Property).where(Property.id == showing.property_id)
            )
            prop = prop_result.scalar_one_or_none()
            prop_addr = prop.address if prop else ""

        date_str = showing.scheduled_date.strftime('%b %d, %Y') if showing.scheduled_date else "TBD"
        time_str = showing.scheduled_time or "TBD"

        msg = (
            f"Blue Deer Property Management\n\n"
            f"Hi{' ' + showing.contact_name.split()[0] if showing.contact_name else ''}! "
            f"Your showing has been scheduled:\n\n"
            f"Property: {prop_addr}\n"
            f"Date: {date_str}\n"
            f"Time: {time_str}\n"
        )
        if showing.description:
            msg += f"\nDetails: {showing.description}\n"
        msg += "\nPlease reply to this message if you have any questions."

        sms_result = await twilio_service.send_sms(phone, msg)
        if sms_result.success:
            logger.info(f"Renter SMS sent to {showing.contact_name} for Showing #{showing.id}")
        else:
            logger.error(f"Failed to SMS renter {showing.contact_name}: {sms_result.error_message}")

        # Store outbound message in DB so it appears in conversations
        try:
            from_number = _normalize_phone(twilio_service.from_number) if twilio_service.from_number else "unknown"
            sms_message = SMSMessage(
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
            logger.error(f"Failed to store renter SMS in DB: {db_err}")

        return sms_result.success
    except Exception as e:
        logger.error(f"Error sending renter showing SMS: {e}")
        return False


# =============================================================================
# Showings CRUD
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def list_showings(
    request: Request,
    status: str = None,
    showing_type: str = None,
    property_id: int = None,
    vendor_id: int = None,
    date_from: str = None,
    date_to: str = None,
):
    """List showings with filters"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(Showing)
            .options(
                selectinload(Showing.property_ref),
                selectinload(Showing.vendor),
            )
        )

        if status:
            query = query.where(Showing.status == ShowingStatus(status))
        if showing_type:
            query = query.where(Showing.showing_type == ShowingType(showing_type))
        if property_id:
            query = query.where(Showing.property_id == property_id)
        if vendor_id:
            query = query.where(Showing.vendor_id == vendor_id)
        if date_from:
            query = query.where(Showing.scheduled_date >= datetime.strptime(date_from, "%Y-%m-%d").date())
        if date_to:
            query = query.where(Showing.scheduled_date <= datetime.strptime(date_to, "%Y-%m-%d").date())

        query = query.order_by(desc(Showing.scheduled_date), desc(Showing.scheduled_time))
        result = await session.execute(query)
        showings = result.scalars().all()

        # Get properties for filter dropdown
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        # Get vendors for filter dropdown
        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

        # Counts by status
        for s in ShowingStatus:
            count_result = await session.execute(
                select(func.count(Showing.id)).where(Showing.status == s)
            )
            setattr(s, '_count', count_result.scalar() or 0)

    return templates.TemplateResponse(
        "showings/list.html",
        {
            "request": request,
            "user": user,
            "showings": showings,
            "properties": properties,
            "vendors": vendors,
            "statuses": ShowingStatus,
            "showing_types": ShowingType,
            "filter_status": status,
            "filter_type": showing_type,
            "filter_property_id": property_id,
            "filter_vendor_id": vendor_id,
            "filter_date_from": date_from,
            "filter_date_to": date_to,
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_showing_form(request: Request):
    """Create showing form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "showings/form.html",
        {
            "request": request,
            "user": user,
            "showing": None,
            "properties": properties,
            "vendors": vendors,
            "showing_types": ShowingType,
            "statuses": ShowingStatus,
        }
    )


@router.post("/create")
async def create_showing(request: Request):
    """Create a new showing"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    property_id_str = form.get("property_id", "").strip()
    vendor_id_str = form.get("vendor_id", "").strip()
    date_str = form.get("scheduled_date", "").strip()
    time_str = form.get("scheduled_time", "").strip()

    if not property_id_str or not date_str or not time_str:
        return RedirectResponse(url="/showings/new", status_code=303)

    async with get_session() as session:
        showing = Showing(
            property_id=int(property_id_str),
            vendor_id=int(vendor_id_str) if vendor_id_str else None,
            title=form["title"],
            showing_type=ShowingType(form.get("showing_type", "other")),
            description=form.get("description", ""),
            scheduled_date=datetime.strptime(date_str, "%Y-%m-%d").date(),
            scheduled_time=time_str,
            status=ShowingStatus.SCHEDULED,
            contact_name=form.get("contact_name", ""),
            contact_phone=form.get("contact_phone", ""),
            notes=form.get("notes", ""),
        )
        session.add(showing)
        await session.flush()
        showing_id = showing.id

        # Auto-send SMS to vendor if assigned
        if showing.vendor_id:
            await _notify_vendor_showing_sms(showing.vendor_id, showing, session)

        # Auto-send SMS to prospective renter if phone provided
        if showing.contact_phone:
            await _notify_renter_showing_sms(showing, session)

    return RedirectResponse(url=f"/showings/{showing_id}", status_code=303)


@router.get("/{showing_id}", response_class=HTMLResponse)
async def showing_detail(request: Request, showing_id: int):
    """Showing detail view"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing)
            .where(Showing.id == showing_id)
            .options(
                selectinload(Showing.property_ref),
                selectinload(Showing.vendor),
            )
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        renter_phone = _normalize_phone(showing.contact_phone) if showing.contact_phone else None

    return templates.TemplateResponse(
        "showings/detail.html",
        {
            "request": request,
            "user": user,
            "showing": showing,
            "statuses": ShowingStatus,
            "renter_phone": renter_phone,
        }
    )


@router.get("/{showing_id}/edit", response_class=HTMLResponse)
async def edit_showing_form(request: Request, showing_id: int):
    """Edit showing form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing)
            .where(Showing.id == showing_id)
            .options(
                selectinload(Showing.property_ref),
                selectinload(Showing.vendor),
            )
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        vendors_result = await session.execute(
            select(Vendor).where(Vendor.is_active == True).order_by(Vendor.name)
        )
        vendors = vendors_result.scalars().all()

    return templates.TemplateResponse(
        "showings/form.html",
        {
            "request": request,
            "user": user,
            "showing": showing,
            "properties": properties,
            "vendors": vendors,
            "showing_types": ShowingType,
            "statuses": ShowingStatus,
        }
    )


@router.post("/{showing_id}/update")
async def update_showing(request: Request, showing_id: int):
    """Update a showing"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    async with get_session() as session:
        result = await session.execute(
            select(Showing).where(Showing.id == showing_id)
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        vendor_str = form.get("vendor_id", "").strip()
        date_str = form.get("scheduled_date", "").strip()
        time_str = form.get("scheduled_time", "").strip()
        old_vendor_id = showing.vendor_id
        new_vendor_id = int(vendor_str) if vendor_str else None

        showing.property_id = int(form["property_id"])
        showing.vendor_id = new_vendor_id
        showing.title = form["title"]
        showing.showing_type = ShowingType(form.get("showing_type", "other"))
        showing.description = form.get("description", "")
        showing.scheduled_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else showing.scheduled_date
        showing.scheduled_time = time_str or showing.scheduled_time
        showing.contact_name = form.get("contact_name", "")
        showing.contact_phone = form.get("contact_phone", "")
        showing.notes = form.get("notes", "")
        showing.updated_at = datetime.utcnow()

        if form.get("status"):
            showing.status = ShowingStatus(form["status"])

        # Notify vendor if newly assigned and checkbox checked
        if new_vendor_id and form.get("notify_vendor") and new_vendor_id != old_vendor_id:
            await _notify_vendor_showing_sms(new_vendor_id, showing, session)

    return RedirectResponse(url=f"/showings/{showing_id}", status_code=303)


@router.post("/{showing_id}/cancel")
async def cancel_showing(request: Request, showing_id: int):
    """Cancel a showing"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing).where(Showing.id == showing_id)
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        showing.status = ShowingStatus.CANCELLED
        showing.updated_at = datetime.utcnow()

    return RedirectResponse(url=f"/showings/{showing_id}", status_code=303)


@router.post("/{showing_id}/complete")
async def complete_showing(request: Request, showing_id: int):
    """Mark showing as complete"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing).where(Showing.id == showing_id)
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        showing.status = ShowingStatus.COMPLETED
        showing.updated_at = datetime.utcnow()

    return RedirectResponse(url=f"/showings/{showing_id}", status_code=303)


@router.post("/{showing_id}/delete")
async def delete_showing(request: Request, showing_id: int):
    """Delete a showing"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing).where(Showing.id == showing_id)
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        await session.delete(showing)

    return RedirectResponse(url="/showings", status_code=303)


@router.post("/{showing_id}/no-show")
async def mark_no_show(request: Request, showing_id: int):
    """Mark showing as no-show and notify tenant"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing)
            .where(Showing.id == showing_id)
            .options(
                selectinload(Showing.property_ref),
                selectinload(Showing.vendor_ref)
            )
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        showing.status = ShowingStatus.NO_SHOW
        showing.updated_at = datetime.utcnow()

        # Send SMS notification to tenant about no-show
        if showing.contact_phone:
            phone = _normalize_phone(showing.contact_phone)
            if phone:
                prop_addr = showing.property_ref.address if showing.property_ref else "the property"
                date_str = showing.scheduled_date.strftime('%b %d, %Y') if showing.scheduled_date else "today"
                time_str = showing.scheduled_time or ""

                msg = (
                    f"Blue Deer Property Management\n\n"
                    f"Hi{' ' + showing.contact_name.split()[0] if showing.contact_name else ''},\n\n"
                    f"We noticed you did not attend the scheduled showing for {prop_addr} "
                    f"on {date_str}{' at ' + time_str if time_str else ''}.\n\n"
                    f"If you'd still like to view this property, please reply to reschedule."
                )

                try:
                    sms_result = await twilio_service.send_sms(phone, msg)
                    if sms_result.success:
                        logger.info(f"No-show SMS sent to {showing.contact_name}")
                    else:
                        logger.error(f"Failed to send no-show SMS: {sms_result.error_message}")

                    # Store in DB
                    from_number = _normalize_phone(twilio_service.from_number) if twilio_service.from_number else "unknown"
                    sms_message = SMSMessage(
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
                except Exception as e:
                    logger.error(f"Error sending no-show SMS: {e}")

    return RedirectResponse(url=f"/showings/{showing_id}?marked=no_show", status_code=303)


@router.get("/{showing_id}/reschedule", response_class=HTMLResponse)
async def reschedule_showing_form(request: Request, showing_id: int):
    """Reschedule showing form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing)
            .where(Showing.id == showing_id)
            .options(
                selectinload(Showing.property_ref),
                selectinload(Showing.vendor_ref)
            )
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

    return templates.TemplateResponse(
        "showings/reschedule.html",
        {
            "request": request,
            "user": user,
            "showing": showing,
        }
    )


@router.post("/{showing_id}/reschedule")
async def reschedule_showing(request: Request, showing_id: int):
    """Reschedule a showing to new date/time"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    date_str = form.get("scheduled_date", "").strip()
    time_str = form.get("scheduled_time", "").strip()

    if not date_str or not time_str:
        return RedirectResponse(url=f"/showings/{showing_id}/reschedule?error=missing_datetime", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Showing)
            .where(Showing.id == showing_id)
            .options(
                selectinload(Showing.property_ref),
                selectinload(Showing.vendor_ref)
            )
        )
        showing = result.scalar_one_or_none()
        if not showing:
            return RedirectResponse(url="/showings", status_code=303)

        old_date = showing.scheduled_date
        old_time = showing.scheduled_time

        showing.scheduled_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        showing.scheduled_time = time_str
        showing.status = ShowingStatus.SCHEDULED  # Reset to scheduled after reschedule
        showing.updated_at = datetime.utcnow()

        # Notify vendor if assigned
        if showing.vendor_id and form.get("notify_vendor"):
            await _notify_vendor_showing_sms(showing.vendor_id, showing, session)

        # Notify renter if contact provided
        if showing.contact_phone and form.get("notify_renter"):
            await _notify_renter_showing_sms(showing, session)

    return RedirectResponse(url=f"/showings/{showing_id}?rescheduled=1", status_code=303)
