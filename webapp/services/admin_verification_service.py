"""SMS verification service for admin/web user phone login"""

import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from database.connection import get_session
from database.models import WebUser, VendorVerification
from webapp.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

EXPIRY_MINUTES = 10
MAX_ATTEMPTS = 3
SEND_WINDOW_MINUTES = 15
MAX_SENDS_PER_WINDOW = 3
GENERIC_CODE_ERROR = "That code is invalid or expired. Request a new code and try again."


def _normalize_phone(phone: str) -> str:
    """Strip to digits only for matching"""
    return ''.join(c for c in phone if c.isdigit())


async def send_admin_verification_code(phone: str) -> dict:
    """Generate a 6-digit code and send it via SMS for admin login.

    Returns: {"success": bool, "error": str|None}
    """
    phone_digits = _normalize_phone(phone)
    if len(phone_digits) < 10 or len(phone_digits) > 15:
        return {"success": False, "error": "Please enter a valid phone number."}

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
            return {"success": True, "error": None}

        recent_cutoff = datetime.utcnow() - timedelta(minutes=SEND_WINDOW_MINUTES)
        result = await session.execute(
            select(VendorVerification).where(
                VendorVerification.vendor_id.is_(None),
                VendorVerification.created_at >= recent_cutoff,
            )
        )
        recent_sends = sum(
            1 for verification in result.scalars().all()
            if _normalize_phone(verification.phone) == phone_digits
        )
        if recent_sends >= MAX_SENDS_PER_WINDOW:
            logger.warning("Admin verification request throttled for ***%s", phone_digits[-4:])
            return {"success": True, "error": None}

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=EXPIRY_MINUTES)

        # Reuse VendorVerification table (works fine for both)
        verification = VendorVerification(
            vendor_id=None,
            phone=phone_digits,
            code=code,
            expires_at=expires_at,
        )
        session.add(verification)

    message = f"Your Blue Deer login code is: {code}\n\nThis code expires in {EXPIRY_MINUTES} minutes."
    sms_phone = f"+1{phone_digits}" if len(phone_digits) == 10 else f"+{phone_digits}"
    sms_result = await twilio_service.send_sms(sms_phone, message)

    if not sms_result.success:
        logger.error("Failed to send admin verification SMS to ***%s: %s", phone_digits[-4:], sms_result.error_message)
        return {"success": False, "error": "Failed to send SMS. Please try again."}

    logger.info("Admin verification code sent to ***%s", phone_digits[-4:])
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
            .where(
                VendorVerification.verified == False,
                VendorVerification.vendor_id.is_(None),
            )
            .order_by(VendorVerification.created_at.desc())
        )
        verifications = result.scalars().all()

        verification = None
        for v in verifications:
            if _normalize_phone(v.phone) == phone_digits:
                verification = v
                break

        if not verification:
            return {"success": False, "user": None, "error": GENERIC_CODE_ERROR}

        if datetime.utcnow() > verification.expires_at:
            return {"success": False, "user": None, "error": GENERIC_CODE_ERROR}

        if verification.attempts >= MAX_ATTEMPTS:
            return {"success": False, "user": None, "error": GENERIC_CODE_ERROR}

        verification.attempts += 1
        if verification.code != code.strip():
            return {"success": False, "user": None, "error": GENERIC_CODE_ERROR}

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
            return {"success": False, "user": None, "error": GENERIC_CODE_ERROR}

        # Update last login
        user.last_login = datetime.utcnow()

        return {"success": True, "user": user, "error": None}
