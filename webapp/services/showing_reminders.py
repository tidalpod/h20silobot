"""Background service: Send SMS reminders 2 hours before showings (tenant only)"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Showing, ShowingStatus

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


async def _send_reminder(showing, prop_addr):
    """Send reminder SMS to prospective renter"""
    from webapp.services.twilio_service import twilio_service

    time_str = _fmt_time_12h(showing.scheduled_time) or "TBD"

    if not showing.contact_phone:
        return 0

    phone = _normalize_phone(showing.contact_phone)
    if not phone:
        return 0

    first_name = showing.contact_name.split()[0] if showing.contact_name else ""
    msg = (
        f"Blue Deer Property Management\n\n"
        f"Hi{' ' + first_name if first_name else ''}! "
        f"Reminder: your showing is in 2 hours.\n\n"
        f"Property: {prop_addr}\n"
        f"Time: {time_str}\n"
        f"\nPlease reply if you need to reschedule."
    )
    result = await twilio_service.send_sms(phone, msg)
    if result.success:
        logger.info(f"Reminder sent to renter {showing.contact_name} for Showing #{showing.id}")
        return 1
    else:
        logger.error(f"Failed to remind renter {showing.contact_name}: {result.error_message}")
        return 0


async def check_and_send_reminders():
    """Check for showings in the next 2 hours and send reminders to tenant"""
    try:
        now = datetime.utcnow()
        today = now.date()

        async with get_session() as session:
            # Get today's showings that haven't been reminded yet
            result = await session.execute(
                select(Showing)
                .options(
                    selectinload(Showing.property_ref),
                )
                .where(
                    Showing.scheduled_date == today,
                    Showing.status.in_([ShowingStatus.SCHEDULED.value, ShowingStatus.CONFIRMED.value]),
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

                # Check if showing is within the next 2 hours
                time_until = (showing_dt - now).total_seconds()
                if 0 < time_until <= 7200:  # Between now and 2 hours from now
                    prop_addr = showing.property_ref.address if showing.property_ref else "Unknown"
                    sent = await _send_reminder(showing, prop_addr)
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
