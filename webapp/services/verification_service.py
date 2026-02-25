"""SMS verification service for tenant portal login"""

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from database.connection import get_session
from database.models import TenantVerification, Tenant
from webapp.services.twilio_service import twilio_service

logger = logging.getLogger(__name__)

EXPIRY_MINUTES = 10
MAX_ATTEMPTS = 3


def _normalize_phone(phone: str) -> str:
    """Strip to digits only for matching"""
    return ''.join(c for c in phone if c.isdigit())


async def send_verification_code(phone: str) -> dict:
    """Generate a 6-digit code and send it via SMS.

    Returns: {"success": bool, "error": str|None}
    """
    code = f"{random.randint(100000, 999999)}"
    expires_at = datetime.utcnow() + timedelta(minutes=EXPIRY_MINUTES)

    # Find tenant by phone
    phone_digits = _normalize_phone(phone)
    tenant_id = None

    async with get_session() as session:
        # Try to match tenant by phone
        result = await session.execute(
            select(Tenant).where(Tenant.is_active == True)
        )
        tenants = result.scalars().all()

        for t in tenants:
            if t.phone and _normalize_phone(t.phone) == phone_digits:
                tenant_id = t.id
                break

        if tenant_id is None:
            return {"success": False, "error": "No tenant found with this phone number"}

        # Store verification record
        verification = TenantVerification(
            tenant_id=tenant_id,
            phone=phone,
            code=code,
            expires_at=expires_at,
        )
        session.add(verification)

    # Send SMS
    message = f"Your Blue Deer verification code is: {code}\n\nThis code expires in {EXPIRY_MINUTES} minutes."
    sms_result = await twilio_service.send_sms(phone, message)

    if not sms_result.success:
        logger.error(f"Failed to send verification SMS to {phone}: {sms_result.error_message}")
        return {"success": False, "error": "Failed to send SMS. Please try again."}

    logger.info(f"Verification code sent to {phone}")
    return {"success": True, "error": None}


async def verify_code(phone: str, code: str) -> dict:
    """Verify a submitted code.

    Returns: {"success": bool, "tenant": dict|None, "error": str|None}
    """
    phone_digits = _normalize_phone(phone)

    async with get_session() as session:
        # Get latest non-verified code for this phone
        result = await session.execute(
            select(TenantVerification)
            .where(
                TenantVerification.verified == False,
            )
            .order_by(TenantVerification.created_at.desc())
        )
        verifications = result.scalars().all()

        verification = None
        for v in verifications:
            if _normalize_phone(v.phone) == phone_digits:
                verification = v
                break

        if not verification:
            return {"success": False, "tenant": None, "error": "No pending verification. Please request a new code."}

        # Check expiry
        if datetime.utcnow() > verification.expires_at:
            return {"success": False, "tenant": None, "error": "Code expired. Please request a new code."}

        # Check attempts
        if verification.attempts >= MAX_ATTEMPTS:
            return {"success": False, "tenant": None, "error": "Too many attempts. Please request a new code."}

        # Check code
        verification.attempts += 1
        if verification.code != code.strip():
            return {"success": False, "tenant": None, "error": f"Invalid code. {MAX_ATTEMPTS - verification.attempts} attempts remaining."}

        # Success - mark as verified
        verification.verified = True

        # Get tenant info
        tenant = None
        if verification.tenant_id:
            from sqlalchemy.orm import selectinload
            result = await session.execute(
                select(Tenant)
                .where(Tenant.id == verification.tenant_id)
                .options(selectinload(Tenant.property_ref))
            )
            tenant_obj = result.scalar_one_or_none()
            if tenant_obj:
                tenant = {
                    "id": tenant_obj.id,
                    "name": tenant_obj.name,
                    "phone": tenant_obj.phone,
                    "email": tenant_obj.email,
                    "property_id": tenant_obj.property_id,
                    "property_address": tenant_obj.property_ref.address if tenant_obj.property_ref else None,
                    "is_section8": tenant_obj.is_section8,
                }

        if not tenant:
            return {"success": False, "tenant": None, "error": "Tenant record not found."}

        return {"success": True, "tenant": tenant, "error": None}
