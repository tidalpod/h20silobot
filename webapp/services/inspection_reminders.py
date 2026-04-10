"""Background service: Send SMS reminders before inspections (tenant + vendor)"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

# All properties are in Michigan (Eastern Time)
try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/Detroit")
except Exception:
    # Fallback: use fixed UTC-4 offset (EDT) if timezone data unavailable
    EASTERN = timezone(timedelta(hours=-4))

from database.connection import get_session
from database.models import (
    Property, Tenant, Vendor, COInspectionVendor,
    InspectionReminderSettings, InspectionReminderLog,
    SMSMessage, MessageDirection,
)

logger = logging.getLogger(__name__)


def _fmt_time_12h(value):
    """Convert '15:00' or '09:30' to '3:00 PM' or '9:30 AM'"""
    if not value:
        return value
    try:
        parts = value.split(":")
        h, m = int(parts[0]), parts[1]
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12}:{m} {ampm}"
    except Exception:
        return value


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


def _lead_time_text(minutes):
    """Human-readable lead time string."""
    if minutes >= 1440:
        days = minutes // 1440
        return f"in {days} day{'s' if days > 1 else ''}"
    if minutes >= 60:
        hrs = minutes // 60
        return f"in {hrs} hour{'s' if hrs > 1 else ''}"
    return f"in {minutes} minutes"


def _inspection_type_label(inspection_type):
    """Human-readable inspection type label."""
    labels = {
        "rental": "Rental Inspection",
        "section8": "Section 8 Inspection",
        "co_mechanical": "CO Mechanical Inspection",
        "co_electrical": "CO Electrical Inspection",
        "co_plumbing": "CO Plumbing Inspection",
        "co_zoning": "CO Zoning Inspection",
        "co_building": "CO Building Inspection",
    }
    return labels.get(inspection_type, inspection_type)


# Map inspection type keys to Property model field names
INSPECTION_FIELDS = {
    "rental": ("rental_inspection_date", "rental_inspection_time"),
    "section8": ("section8_inspection_date", "section8_inspection_time"),
    "co_mechanical": ("co_mechanical_date", "co_mechanical_time"),
    "co_electrical": ("co_electrical_date", "co_electrical_time"),
    "co_plumbing": ("co_plumbing_date", "co_plumbing_time"),
    "co_zoning": ("co_zoning_date", "co_zoning_time"),
    "co_building": ("co_building_date", "co_building_time"),
}


async def _send_tenant_reminders(property_id, prop_addr, inspection_type, time_str, lead_minutes, session):
    """Send reminder SMS to all active tenants at a property."""
    from webapp.services.twilio_service import twilio_service

    result = await session.execute(
        select(Tenant).where(
            Tenant.property_id == property_id,
            Tenant.is_active == True,
        )
    )
    tenants = result.scalars().all()
    sent = 0

    label = _inspection_type_label(inspection_type)
    formatted_time = _fmt_time_12h(time_str) or "TBD"

    for tenant in tenants:
        if not tenant.phone:
            continue
        phone = _normalize_phone(tenant.phone)
        if not phone:
            continue

        first_name = tenant.name.split()[0] if tenant.name else ""
        msg = (
            f"Blue Deer Property Management\n\n"
            f"Hi{' ' + first_name if first_name else ''}! "
            f"Reminder: your {label} is {_lead_time_text(lead_minutes)}.\n\n"
            f"Property: {prop_addr}\n"
            f"Time: {formatted_time}\n"
            f"\nPlease ensure the unit is accessible. Reply with any questions."
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
                created_at=datetime.utcnow(),
            )
            session.add(sms_message)
        except Exception as db_err:
            logger.error(f"Failed to store inspection reminder SMS in DB: {db_err}")

        if sms_result.success:
            logger.info(f"Inspection reminder sent to tenant {tenant.name} at {phone}")
            sent += 1
        else:
            logger.warning(f"Failed to send inspection reminder to {tenant.name}: {sms_result.error_message}")

    return sent


async def _send_vendor_reminder(property_id, prop_addr, inspection_type, time_str, lead_minutes, session):
    """Send reminder SMS to the vendor assigned to a CO inspection type."""
    from webapp.services.twilio_service import twilio_service

    # Only CO inspections have vendor assignments
    if not inspection_type.startswith("co_"):
        return 0

    co_type = inspection_type.replace("co_", "")  # e.g. "mechanical"

    result = await session.execute(
        select(COInspectionVendor)
        .where(
            COInspectionVendor.property_id == property_id,
            COInspectionVendor.inspection_type == co_type,
        )
        .options(selectinload(COInspectionVendor.vendor))
    )
    assignment = result.scalar_one_or_none()
    if not assignment or not assignment.vendor or not assignment.vendor.phone:
        return 0

    vendor = assignment.vendor
    phone = _normalize_phone(vendor.phone)
    if not phone:
        return 0

    label = _inspection_type_label(inspection_type)
    formatted_time = _fmt_time_12h(time_str) or "TBD"

    msg = (
        f"Blue Deer - Inspection Reminder\n\n"
        f"Hi {vendor.name}! Reminder: you have a {label} {_lead_time_text(lead_minutes)}.\n\n"
        f"Property: {prop_addr}\n"
        f"Time: {formatted_time}\n"
    )

    sms_result = await twilio_service.send_sms(phone, msg)
    if sms_result.success:
        logger.info(f"Inspection reminder sent to vendor {vendor.name} for {inspection_type} at {prop_addr}")
        return 1
    else:
        logger.error(f"Failed to remind vendor {vendor.name}: {sms_result.error_message}")
        return 0


async def check_and_send_inspection_reminders():
    """Check for upcoming inspections and send reminders based on admin settings."""
    try:
        now = datetime.now(EASTERN)
        today = now.date()

        async with get_session() as session:
            # Load reminder settings (fallback to defaults if missing)
            settings_result = await session.execute(
                select(InspectionReminderSettings).limit(1)
            )
            settings = settings_result.scalar_one_or_none()
            remind_tenant = settings.remind_tenant if settings else True
            remind_vendor = settings.remind_vendor if settings else False
            lead_time_minutes = settings.lead_time_minutes if settings else 120
            lead_time_seconds = lead_time_minutes * 60

            # Get all active properties
            result = await session.execute(
                select(Property).where(Property.is_active == True)
            )
            properties = result.scalars().all()

            # Look ahead enough days to cover the lead time window
            max_lookahead_days = (lead_time_minutes // 1440) + 1

            for prop in properties:
                for insp_type, (date_field, time_field) in INSPECTION_FIELDS.items():
                    insp_date = getattr(prop, date_field)
                    insp_time = getattr(prop, time_field)

                    if not insp_date or not insp_time:
                        continue
                    days_away = (insp_date - today).days
                    if days_away < 0 or days_away > max_lookahead_days:
                        continue

                    # Parse time (format "HH:MM") — treat as Eastern
                    try:
                        hour, minute = map(int, insp_time.split(":"))
                        naive_dt = datetime.combine(insp_date, datetime.min.time().replace(hour=hour, minute=minute))
                        insp_dt = naive_dt.replace(tzinfo=EASTERN)
                    except (ValueError, AttributeError):
                        continue

                    # Check if within lead time window
                    time_until = (insp_dt - now).total_seconds()
                    if not (0 < time_until <= lead_time_seconds):
                        continue

                    # Check if already reminded
                    log_result = await session.execute(
                        select(InspectionReminderLog).where(
                            InspectionReminderLog.property_id == prop.id,
                            InspectionReminderLog.inspection_type == insp_type,
                            InspectionReminderLog.inspection_date == insp_date,
                        )
                    )
                    if log_result.scalar_one_or_none():
                        continue

                    prop_addr = prop.address or "Unknown"

                    # Create log record BEFORE sending to prevent re-sends on retry
                    session.add(InspectionReminderLog(
                        property_id=prop.id,
                        inspection_type=insp_type,
                        inspection_date=insp_date,
                        sent_at=datetime.utcnow(),
                    ))
                    await session.commit()

                    sent = 0
                    if remind_tenant:
                        sent += await _send_tenant_reminders(
                            prop.id, prop_addr, insp_type, insp_time, lead_time_minutes, session
                        )

                    if remind_vendor:
                        sent += await _send_vendor_reminder(
                            prop.id, prop_addr, insp_type, insp_time, lead_time_minutes, session
                        )

                    if sent > 0:
                        await session.commit()
                        logger.info(f"Inspection {insp_type} @ {prop_addr}: sent {sent} reminder(s)")
                    else:
                        logger.warning(f"Inspection {insp_type} @ {prop_addr} on {insp_date}: "
                                       f"in lead-time window but 0 reminders sent (no tenant phone?)")

    except Exception as e:
        logger.error(f"Error in inspection reminder check: {e}")


async def inspection_reminder_loop():
    """Run the inspection reminder check every 60 seconds."""
    logger.info("Inspection reminder service started")
    while True:
        try:
            await check_and_send_inspection_reminders()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Inspection reminder loop error (will retry): {e}")
        await asyncio.sleep(60)
