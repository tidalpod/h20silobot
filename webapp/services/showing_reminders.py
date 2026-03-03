"""Background service: Send SMS reminders 1 hour before showings"""

import asyncio
import logging
from datetime import datetime, timedelta, date

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Showing, ShowingStatus, Vendor, Property

logger = logging.getLogger(__name__)


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


async def _send_reminder(showing, vendor, prop_addr):
    """Send reminder SMS to vendor and prospective renter"""
    from webapp.services.twilio_service import twilio_service
    from database.models import SMSMessage, MessageDirection

    date_str = showing.scheduled_date.strftime('%b %d, %Y') if showing.scheduled_date else "TBD"
    time_str = showing.scheduled_time or "TBD"

    sent_count = 0

    # Remind vendor
    if vendor and vendor.phone:
        phone = _normalize_phone(vendor.phone)
        if phone:
            msg = (
                f"Blue Deer - Showing Reminder\n\n"
                f"You have a showing in 1 hour:\n\n"
                f"Title: {showing.title}\n"
                f"Property: {prop_addr}\n"
                f"Time: {time_str}\n"
            )
            if showing.contact_name:
                msg += f"Prospective Renter: {showing.contact_name}"
                if showing.contact_phone:
                    msg += f" ({showing.contact_phone})"
                msg += "\n"

            result = await twilio_service.send_sms(phone, msg)
            if result.success:
                sent_count += 1
                logger.info(f"Reminder sent to vendor {vendor.name} for Showing #{showing.id}")
            else:
                logger.error(f"Failed to remind vendor {vendor.name}: {result.error_message}")

    # Remind prospective renter
    if showing.contact_phone:
        phone = _normalize_phone(showing.contact_phone)
        if phone:
            first_name = showing.contact_name.split()[0] if showing.contact_name else ""
            msg = (
                f"Blue Deer Property Management\n\n"
                f"Hi{' ' + first_name if first_name else ''}! "
                f"Reminder: your showing is in 1 hour.\n\n"
                f"Property: {prop_addr}\n"
                f"Time: {time_str}\n"
                f"\nPlease reply if you need to reschedule."
            )
            result = await twilio_service.send_sms(phone, msg)
            if result.success:
                sent_count += 1
                logger.info(f"Reminder sent to renter {showing.contact_name} for Showing #{showing.id}")
            else:
                logger.error(f"Failed to remind renter {showing.contact_name}: {result.error_message}")

    return sent_count


async def check_and_send_reminders():
    """Check for showings in the next hour and send reminders"""
    try:
        now = datetime.utcnow()
        today = now.date()

        async with get_session() as session:
            # Get today's showings that haven't been reminded yet
            result = await session.execute(
                select(Showing)
                .options(
                    selectinload(Showing.vendor),
                    selectinload(Showing.property_ref),
                )
                .where(
                    Showing.scheduled_date == today,
                    Showing.status.in_([ShowingStatus.SCHEDULED, ShowingStatus.CONFIRMED]),
                    Showing.reminder_sent_at.is_(None),
                )
            )
            showings = result.scalars().all()

            for showing in showings:
                # Parse scheduled_time (format "HH:MM")
                try:
                    hour, minute = map(int, showing.scheduled_time.split(":"))
                    showing_dt = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
                except (ValueError, AttributeError):
                    continue

                # Check if showing is within the next 60-90 minutes
                # (gives a 30-min window so we don't miss it between checks)
                time_until = (showing_dt - now).total_seconds()
                if 0 < time_until <= 5400:  # Between now and 90 minutes from now
                    prop_addr = showing.property_ref.address if showing.property_ref else "Unknown"
                    sent = await _send_reminder(showing, showing.vendor, prop_addr)
                    if sent > 0:
                        showing.reminder_sent_at = now
                        logger.info(f"Showing #{showing.id}: sent {sent} reminder(s)")

            await session.commit()

    except Exception as e:
        logger.error(f"Error in showing reminder check: {e}")


async def reminder_loop():
    """Run the reminder check every 60 seconds"""
    logger.info("Showing reminder service started")
    while True:
        await check_and_send_reminders()
        await asyncio.sleep(60)
