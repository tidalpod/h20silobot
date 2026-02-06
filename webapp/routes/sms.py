"""SMS Chat routes for bidirectional SMS conversations"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from pathlib import Path

from database.connection import get_session
from database.models import SMSMessage, Tenant, Property, MessageDirection
from webapp.services.twilio_service import twilio_service
from webapp.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sms", tags=["sms"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def normalize_phone(phone: str) -> Optional[str]:
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
    else:
        return f"+{digits}"


# =============================================================================
# Twilio Webhook (Incoming SMS)
# =============================================================================

@router.post("/webhook/incoming")
async def twilio_incoming_webhook(
    request: Request,
    From: str = Form(...),
    To: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(None),
    AccountSid: str = Form(None),
):
    """
    Twilio webhook for incoming SMS messages.

    Twilio sends a POST request here when someone texts our number.
    We store the message and try to match it to a tenant.
    """
    logger.info(f"Incoming SMS from {From}: {Body[:50]}...")

    try:
        async with get_session() as session:
            # Normalize the from number
            from_number = normalize_phone(From)
            to_number = normalize_phone(To)

            # Try to find the tenant by phone number
            tenant_id = None
            property_id = None

            if from_number:
                result = await session.execute(
                    select(Tenant)
                    .where(Tenant.is_active == True)
                    .options(selectinload(Tenant.property_ref))
                )
                tenants = result.scalars().all()

                # Match phone numbers (comparing normalized versions)
                for tenant in tenants:
                    if tenant.phone:
                        tenant_phone = normalize_phone(tenant.phone)
                        if tenant_phone == from_number:
                            tenant_id = tenant.id
                            property_id = tenant.property_id
                            logger.info(f"Matched incoming SMS to tenant: {tenant.name}")
                            break

            # Store the incoming message
            sms_message = SMSMessage(
                tenant_id=tenant_id,
                property_id=property_id,
                from_number=from_number or From,
                to_number=to_number or To,
                body=Body,
                direction=MessageDirection.INBOUND,
                twilio_sid=MessageSid,
                status="received",
                created_at=datetime.utcnow()
            )
            session.add(sms_message)
            await session.commit()

            logger.info(f"Stored incoming SMS message, tenant_id={tenant_id}")

        # Return empty TwiML response (Twilio expects XML)
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        logger.error(f"Error processing incoming SMS: {e}")
        # Still return valid TwiML so Twilio doesn't retry
        twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
        return Response(content=twiml, media_type="application/xml")


# =============================================================================
# Conversation API
# =============================================================================

@router.get("/conversation/{tenant_id}")
async def get_conversation(tenant_id: int, request: Request):
    """Get SMS conversation history for a tenant"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_session() as session:
        # Get tenant with property
        result = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .options(selectinload(Tenant.property_ref))
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if not tenant.phone:
            return JSONResponse({
                "tenant": {"id": tenant.id, "name": tenant.name, "phone": None},
                "messages": [],
                "error": "Tenant has no phone number"
            })

        # Normalize tenant's phone for matching
        tenant_phone = normalize_phone(tenant.phone)
        our_phone = normalize_phone(twilio_service.from_number) if twilio_service.from_number else None

        # Get all messages for this tenant by tenant_id OR phone number match
        result = await session.execute(
            select(SMSMessage)
            .where(
                or_(
                    SMSMessage.tenant_id == tenant_id,
                    SMSMessage.from_number == tenant_phone,
                    SMSMessage.to_number == tenant_phone
                )
            )
            .order_by(SMSMessage.created_at.asc())
        )
        messages = result.scalars().all()

        return JSONResponse({
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "phone": tenant.phone,
                "property": tenant.property_ref.address if tenant.property_ref else None
            },
            "our_phone": our_phone,
            "messages": [
                {
                    "id": msg.id,
                    "body": msg.body,
                    "direction": msg.direction.value,
                    "status": msg.status,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    "from_number": msg.from_number,
                    "to_number": msg.to_number
                }
                for msg in messages
            ]
        })


@router.post("/send/{tenant_id}")
async def send_sms_to_tenant(
    tenant_id: int,
    request: Request,
    message: str = Form(...)
):
    """Send an SMS to a tenant and store in conversation"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    async with get_session() as session:
        # Get tenant
        result = await session.execute(
            select(Tenant)
            .where(Tenant.id == tenant_id)
            .options(selectinload(Tenant.property_ref))
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if not tenant.phone:
            raise HTTPException(status_code=400, detail="Tenant has no phone number")

        # Send SMS via Twilio
        result = await twilio_service.send_sms(tenant.phone, message)

        # Store outbound message
        from_number = normalize_phone(twilio_service.from_number) if twilio_service.from_number else "unknown"
        to_number = normalize_phone(tenant.phone)

        sms_message = SMSMessage(
            tenant_id=tenant_id,
            property_id=tenant.property_id,
            from_number=from_number,
            to_number=to_number,
            body=message,
            direction=MessageDirection.OUTBOUND,
            twilio_sid=result.message_sid if result.success else None,
            status="sent" if result.success else "failed",
            created_at=datetime.utcnow()
        )
        session.add(sms_message)
        await session.commit()

        if result.success:
            return JSONResponse({
                "success": True,
                "message_id": sms_message.id,
                "twilio_sid": result.message_sid
            })
        else:
            return JSONResponse({
                "success": False,
                "error": result.error_message
            }, status_code=400)


# =============================================================================
# Recent Conversations List
# =============================================================================

@router.get("/recent")
async def get_recent_conversations(request: Request):
    """Get list of recent SMS conversations"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_session() as session:
        # Get all tenants with phone numbers who have SMS messages
        result = await session.execute(
            select(Tenant)
            .where(Tenant.is_active == True)
            .where(Tenant.phone != None)
            .options(
                selectinload(Tenant.property_ref),
                selectinload(Tenant.sms_messages)
            )
        )
        tenants = result.scalars().all()

        conversations = []
        for tenant in tenants:
            if tenant.sms_messages:
                # Get most recent message
                latest_msg = max(tenant.sms_messages, key=lambda m: m.created_at or datetime.min)
                unread_count = sum(
                    1 for m in tenant.sms_messages
                    if m.direction == MessageDirection.INBOUND and m.status == "received"
                )
                conversations.append({
                    "tenant_id": tenant.id,
                    "tenant_name": tenant.name,
                    "tenant_phone": tenant.phone,
                    "property_address": tenant.property_ref.address if tenant.property_ref else "Unknown",
                    "last_message": latest_msg.body[:50] + "..." if len(latest_msg.body) > 50 else latest_msg.body,
                    "last_message_time": latest_msg.created_at.isoformat() if latest_msg.created_at else None,
                    "last_direction": latest_msg.direction.value,
                    "message_count": len(tenant.sms_messages),
                    "unread_count": unread_count
                })

        # Sort by most recent message
        conversations.sort(
            key=lambda c: c["last_message_time"] or "",
            reverse=True
        )

        return JSONResponse({"conversations": conversations})


# =============================================================================
# Unmatched Messages
# =============================================================================

@router.get("/unmatched")
async def get_unmatched_messages(request: Request):
    """Get SMS messages that couldn't be matched to a tenant"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_session() as session:
        result = await session.execute(
            select(SMSMessage)
            .where(SMSMessage.tenant_id == None)
            .where(SMSMessage.direction == MessageDirection.INBOUND)
            .order_by(SMSMessage.created_at.desc())
            .limit(50)
        )
        messages = result.scalars().all()

        return JSONResponse({
            "messages": [
                {
                    "id": msg.id,
                    "from_number": msg.from_number,
                    "body": msg.body,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None
                }
                for msg in messages
            ]
        })
