"""SMS verification service for tenant portal login"""

import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from database.connection import get_session
from database.models import TenantVerification, Tenant
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


def _sms_phone(phone_digits: str) -> str:
    """Return an E.164-style number for common US inputs."""
    if len(phone_digits) == 10:
        return f"+1{phone_digits}"
    return f"+{phone_digits}"


def _masked_phone(phone_digits: str) -> str:
    return f"***-***-{phone_digits[-4:]}" if len(phone_digits) >= 4 else "masked number"


async def send_verification_code(phone: str) -> dict:
    """Generate a 6-digit code and send it via SMS.

    Returns: {"success": bool, "error": str|None}
    """
    # Find tenant by phone
    phone_digits = _normalize_phone(phone)
    if len(phone_digits) < 10 or len(phone_digits) > 15:
        return {"success": False, "error": "Please enter a valid phone number."}

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
            # Do not reveal whether a phone number is registered.
            return {"success": True, "error": None}

        recent_cutoff = datetime.utcnow() - timedelta(minutes=SEND_WINDOW_MINUTES)
        result = await session.execute(
            select(TenantVerification).where(TenantVerification.created_at >= recent_cutoff)
        )
        recent_sends = sum(
            1 for verification in result.scalars().all()
            if _normalize_phone(verification.phone) == phone_digits
        )
        if recent_sends >= MAX_SENDS_PER_WINDOW:
            logger.warning("Verification request throttled for %s", _masked_phone(phone_digits))
            return {"success": True, "error": None}

        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=EXPIRY_MINUTES)

        # Store verification record
        verification = TenantVerification(
            tenant_id=tenant_id,
            phone=phone_digits,
            code=code,
            expires_at=expires_at,
        )
        session.add(verification)

    # Send SMS
    message = f"Your Blue Deer verification code is: {code}\n\nThis code expires in {EXPIRY_MINUTES} minutes."
    sms_result = await twilio_service.send_sms(_sms_phone(phone_digits), message)

    if not sms_result.success:
        logger.error(
            "Failed to send verification SMS to %s: %s",
            _masked_phone(phone_digits),
            sms_result.error_message,
        )
        return {"success": False, "error": "Failed to send SMS. Please try again."}

    logger.info("Verification code sent to %s", _masked_phone(phone_digits))
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
            return {"success": False, "tenant": None, "error": GENERIC_CODE_ERROR}

        # Check expiry
        if datetime.utcnow() > verification.expires_at:
            return {"success": False, "tenant": None, "error": GENERIC_CODE_ERROR}

        # Check attempts
        if verification.attempts >= MAX_ATTEMPTS:
            return {"success": False, "tenant": None, "error": GENERIC_CODE_ERROR}

        # Check code
        verification.attempts += 1
        if verification.code != code.strip():
            return {"success": False, "tenant": None, "error": GENERIC_CODE_ERROR}

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
            return {"success": False, "tenant": None, "error": GENERIC_CODE_ERROR}

        return {"success": True, "tenant": tenant, "error": None}
