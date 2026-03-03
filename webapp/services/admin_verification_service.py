"""SMS verification service for admin/web user phone login"""

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from database.connection import get_session
from database.models import WebUser, VendorVerification
from webapp.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

EXPIRY_MINUTES = 10
MAX_ATTEMPTS = 3


def _normalize_phone(phone: str) -> str:
    """Strip to digits only for matching"""
    return ''.join(c for c in phone if c.isdigit())


async def send_admin_verification_code(phone: str) -> dict:
    """Generate a 6-digit code and send it via SMS for admin login.

    Returns: {"success": bool, "error": str|None}
    """
    code = f"{random.randint(100000, 999999)}"
    expires_at = datetime.utcnow() + timedelta(minutes=EXPIRY_MINUTES)

    phone_digits = _normalize_phone(phone)

    async with get_session() as session:
        # Find active web user with this phone
        result = await session.execute(
            select(WebUser).where(WebUser.is_active == True)
        )
        users = result.scalars().all()

        user_id = None
        for u in users:
            if u.phone and _normalize_phone(u.phone) == phone_digits:
                user_id = u.id
                break

        if user_id is None:
            return {"success": False, "error": "No account found with this phone number"}

        # Reuse VendorVerification table (works fine for both)
        verification = VendorVerification(
            vendor_id=None,
            phone=phone,
            code=code,
            expires_at=expires_at,
        )
        session.add(verification)

    message = f"Your Blue Deer login code is: {code}\n\nThis code expires in {EXPIRY_MINUTES} minutes."
    sms_result = await twilio_service.send_sms(phone, message)

    if not sms_result.success:
        logger.error(f"Failed to send admin verification SMS to {phone}: {sms_result.error_message}")
        return {"success": False, "error": "Failed to send SMS. Please try again."}

    logger.info(f"Admin verification code sent to {phone}")
    return {"success": True, "error": None}


async def verify_admin_code(phone: str, code: str) -> dict:
    """Verify a submitted code for admin login.

    Returns: {"success": bool, "user": WebUser|None, "error": str|None}
    """
    phone_digits = _normalize_phone(phone)

    async with get_session() as session:
        # Find latest unverified code for this phone
        result = await session.execute(
            select(VendorVerification)
            .where(VendorVerification.verified == False)
            .order_by(VendorVerification.created_at.desc())
        )
        verifications = result.scalars().all()

        verification = None
        for v in verifications:
            if _normalize_phone(v.phone) == phone_digits:
                verification = v
                break

        if not verification:
            return {"success": False, "user": None, "error": "No pending verification. Please request a new code."}

        if datetime.utcnow() > verification.expires_at:
            return {"success": False, "user": None, "error": "Code expired. Please request a new code."}

        if verification.attempts >= MAX_ATTEMPTS:
            return {"success": False, "user": None, "error": "Too many attempts. Please request a new code."}

        verification.attempts += 1
        if verification.code != code.strip():
            remaining = MAX_ATTEMPTS - verification.attempts
            return {"success": False, "user": None, "error": f"Invalid code. {remaining} attempt{'s' if remaining != 1 else ''} remaining."}

        # Success
        verification.verified = True

        # Find the web user
        result = await session.execute(
            select(WebUser).where(WebUser.is_active == True)
        )
        users = result.scalars().all()
        user = None
        for u in users:
            if u.phone and _normalize_phone(u.phone) == phone_digits:
                user = u
                break

        if not user:
            return {"success": False, "user": None, "error": "Account not found."}

        # Update last login
        user.last_login = datetime.utcnow()

        return {"success": True, "user": user, "error": None}
