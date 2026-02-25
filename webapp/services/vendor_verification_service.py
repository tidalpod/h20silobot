"""SMS verification service for vendor portal login"""

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from database.connection import get_session
from database.models import VendorVerification, Vendor
from webapp.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

EXPIRY_MINUTES = 10
MAX_ATTEMPTS = 3


def _normalize_phone(phone: str) -> str:
    """Strip to digits only for matching"""
    return ''.join(c for c in phone if c.isdigit())


async def send_vendor_verification_code(phone: str) -> dict:
    """Generate a 6-digit code and send it via SMS.

    Returns: {"success": bool, "error": str|None}
    """
    code = f"{random.randint(100000, 999999)}"
    expires_at = datetime.utcnow() + timedelta(minutes=EXPIRY_MINUTES)

    phone_digits = _normalize_phone(phone)
    vendor_id = None

    async with get_session() as session:
        result = await session.execute(
            select(Vendor).where(Vendor.is_active == True)
        )
        vendors = result.scalars().all()

        for v in vendors:
            if v.phone and _normalize_phone(v.phone) == phone_digits:
                vendor_id = v.id
                break

        if vendor_id is None:
            return {"success": False, "error": "No vendor found with this phone number"}

        verification = VendorVerification(
            vendor_id=vendor_id,
            phone=phone,
            code=code,
            expires_at=expires_at,
        )
        session.add(verification)

    message = f"Your Blue Deer vendor portal code is: {code}\n\nThis code expires in {EXPIRY_MINUTES} minutes."
    sms_result = await twilio_service.send_sms(phone, message)

    if not sms_result.success:
        logger.error(f"Failed to send vendor verification SMS to {phone}: {sms_result.error_message}")
        return {"success": False, "error": "Failed to send SMS. Please try again."}

    logger.info(f"Vendor verification code sent to {phone}")
    return {"success": True, "error": None}


async def verify_vendor_code(phone: str, code: str) -> dict:
    """Verify a submitted code.

    Returns: {"success": bool, "vendor": dict|None, "error": str|None}
    """
    phone_digits = _normalize_phone(phone)

    async with get_session() as session:
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
            return {"success": False, "vendor": None, "error": "No pending verification. Please request a new code."}

        if datetime.utcnow() > verification.expires_at:
            return {"success": False, "vendor": None, "error": "Code expired. Please request a new code."}

        if verification.attempts >= MAX_ATTEMPTS:
            return {"success": False, "vendor": None, "error": "Too many attempts. Please request a new code."}

        verification.attempts += 1
        if verification.code != code.strip():
            return {"success": False, "vendor": None, "error": f"Invalid code. {MAX_ATTEMPTS - verification.attempts} attempts remaining."}

        # Success
        verification.verified = True

        vendor = None
        if verification.vendor_id:
            result = await session.execute(
                select(Vendor).where(Vendor.id == verification.vendor_id)
            )
            vendor_obj = result.scalar_one_or_none()
            if vendor_obj:
                vendor = {
                    "id": vendor_obj.id,
                    "name": vendor_obj.name,
                    "phone": vendor_obj.phone,
                    "email": vendor_obj.email,
                    "company": vendor_obj.company,
                    "specialty": vendor_obj.specialty,
                }

        if not vendor:
            return {"success": False, "vendor": None, "error": "Vendor record not found."}

        return {"success": True, "vendor": vendor, "error": None}
