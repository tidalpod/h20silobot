"""Notification management routes"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    Notification, NotificationChannel, NotificationStatus,
    Tenant, Property, WaterBill, BillStatus
)
from webapp.auth.dependencies import get_current_user
from webapp.services.twilio_service import twilio_service
from webapp.services.email_service import email_service
from webapp.config import web_config

router = APIRouter(tags=["notifications"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# Notification message templates
MESSAGE_TEMPLATES = {
    "overdue": {
        "subject": "Water Bill Overdue Notice",
        "sms": "NOTICE: Your water bill for {address} is OVERDUE. Amount due: ${amount}. Due date: {due_date}. Please pay immediately to avoid late fees.",
        "email": """
Dear {tenant_name},

This is a reminder that your water bill for the property at:

{address}

is currently OVERDUE.

Amount Due: ${amount}
Due Date: {due_date}

Please make your payment as soon as possible to avoid additional late fees or service interruption.

You can pay online at: https://bsaonline.com/?uid=305

If you have already made this payment, please disregard this notice.

Thank you,
Property Management
""",
    },
    "due_soon": {
        "subject": "Water Bill Due Soon",
        "sms": "REMINDER: Your water bill for {address} is due soon. Amount: ${amount}. Due date: {due_date}.",
        "email": """
Dear {tenant_name},

This is a friendly reminder that your water bill for the property at:

{address}

is due soon.

Amount Due: ${amount}
Due Date: {due_date}

You can pay online at: https://bsaonline.com/?uid=305

Thank you,
Property Management
""",
    },
    "custom": {
        "subject": "Property Notice",
        "sms": "{message}",
        "email": """
Dear {tenant_name},

{message}

Property: {address}

Thank you,
Property Management
""",
    },
}


@router.get("/chat", response_class=HTMLResponse)
async def sms_chat(request: Request):
    """SMS chat conversations page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "notifications/chat.html",
        {
            "request": request,
            "user": user,
        }
    )


@router.get("/", response_class=HTMLResponse)
async def list_notifications(request: Request, status: str = None):
    """List notification history"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(Notification)
            .options(
                selectinload(Notification.tenant),
                selectinload(Notification.property)
            )
        )

        if status:
            try:
                status_enum = NotificationStatus(status)
                query = query.where(Notification.status == status_enum)
            except ValueError:
                pass

        result = await session.execute(
            query.order_by(Notification.created_at.desc()).limit(100)
        )
        notifications = result.scalars().all()

    return templates.TemplateResponse(
        "notifications/history.html",
        {
            "request": request,
            "user": user,
            "notifications": notifications,
            "status_filter": status,
            "has_twilio": web_config.has_twilio,
            "has_email": web_config.has_sendgrid or web_config.has_smtp,
        }
    )


@router.get("/compose", response_class=HTMLResponse)
async def compose_notification(
    request: Request,
    property_id: int = None,
    tenant_id: int = None,
    template: str = "custom"
):
    """Compose a new notification"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get properties for dropdown
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .options(selectinload(Property.tenants), selectinload(Property.bills))
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        selected_property = None
        selected_tenant = None
        latest_bill = None

        if property_id:
            for prop in properties:
                if prop.id == property_id:
                    selected_property = prop
                    if prop.bills:
                        latest_bill = prop.bills[0]
                    break

        if tenant_id:
            result = await session.execute(
                select(Tenant)
                .where(Tenant.id == tenant_id)
                .options(selectinload(Tenant.property_ref))
            )
            selected_tenant = result.scalar_one_or_none()
            if selected_tenant:
                selected_property = selected_tenant.property_ref

        # Get active tenants for selected property
        tenants = []
        if selected_property:
            tenants = [t for t in selected_property.tenants if t.is_active]

    return templates.TemplateResponse(
        "notifications/compose.html",
        {
            "request": request,
            "user": user,
            "properties": properties,
            "tenants": tenants,
            "selected_property": selected_property,
            "selected_tenant": selected_tenant,
            "latest_bill": latest_bill,
            "template": template,
            "templates": list(MESSAGE_TEMPLATES.keys()),
            "has_twilio": web_config.has_twilio,
            "has_email": web_config.has_sendgrid or web_config.has_smtp,
        }
    )


@router.post("/send", response_class=HTMLResponse)
async def send_notification(
    request: Request,
    property_id: int = Form(...),
    tenant_id: int = Form(None),
    channel: str = Form(...),
    recipient: str = Form(...),
    subject: str = Form(""),
    message: str = Form(...)
):
    """Send a notification"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Validate channel
    try:
        channel_enum = NotificationChannel(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel")

    async with get_session() as session:
        # Get property
        result = await session.execute(
            select(Property)
            .where(Property.id == property_id)
            .options(selectinload(Property.bills))
        )
        prop = result.scalar_one_or_none()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # Get tenant if specified
        tenant = None
        if tenant_id:
            result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = result.scalar_one_or_none()

        # Get latest bill
        bill_id = None
        if prop.bills:
            bill_id = prop.bills[0].id

        # Create notification record
        notification = Notification(
            tenant_id=tenant_id,
            property_id=property_id,
            bill_id=bill_id,
            channel=channel_enum,
            recipient=recipient,
            subject=subject if channel_enum == NotificationChannel.EMAIL else None,
            message=message,
            status=NotificationStatus.PENDING,
        )
        session.add(notification)
        await session.flush()

        # Send notification
        if channel_enum == NotificationChannel.SMS:
            result = await twilio_service.send_sms(recipient, message)
        else:
            result = await email_service.send_email(
                recipient,
                subject,
                message,
                html_body=message.replace('\n', '<br>')
            )

        # Update notification status
        if result.success:
            notification.status = NotificationStatus.SENT
            notification.external_id = result.message_sid if hasattr(result, 'message_sid') else result.message_id
            notification.sent_at = datetime.utcnow()
        else:
            notification.status = NotificationStatus.FAILED
            notification.error_message = result.error_message

        await session.commit()

    # Redirect back to notifications with success/error message
    return RedirectResponse(url="/notifications", status_code=303)


@router.get("/bulk", response_class=HTMLResponse)
async def bulk_notification_form(request: Request, type: str = "overdue"):
    """Show bulk notification form for overdue/due soon properties"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get properties with matching status
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .options(
                selectinload(Property.bills),
                selectinload(Property.tenants)
            )
            .order_by(Property.address)
        )
        all_properties = result.scalars().all()

        # Filter by bill status
        target_status = BillStatus.OVERDUE if type == "overdue" else BillStatus.DUE_SOON
        properties_with_tenants = []

        for prop in all_properties:
            if prop.bills:
                bill_status = prop.bills[0].calculate_status()
                if bill_status == target_status:
                    active_tenants = [t for t in prop.tenants if t.is_active and (t.phone or t.email)]
                    if active_tenants:
                        properties_with_tenants.append({
                            "property": prop,
                            "bill": prop.bills[0],
                            "tenants": active_tenants
                        })

    return templates.TemplateResponse(
        "notifications/bulk.html",
        {
            "request": request,
            "user": user,
            "type": type,
            "properties": properties_with_tenants,
            "template": MESSAGE_TEMPLATES.get(type, MESSAGE_TEMPLATES["custom"]),
            "has_twilio": web_config.has_twilio,
            "has_email": web_config.has_sendgrid or web_config.has_smtp,
        }
    )


@router.post("/bulk/send")
async def send_bulk_notifications(
    request: Request,
    type: str = Form("overdue"),
    channel: str = Form("sms"),
    property_ids: list[int] = Form(...)
):
    """Send bulk notifications to selected properties"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        channel_enum = NotificationChannel(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid channel")

    template = MESSAGE_TEMPLATES.get(type, MESSAGE_TEMPLATES["custom"])
    sent_count = 0
    failed_count = 0

    async with get_session() as session:
        for property_id in property_ids:
            # Get property with tenants and bills
            result = await session.execute(
                select(Property)
                .where(Property.id == property_id)
                .options(
                    selectinload(Property.bills),
                    selectinload(Property.tenants)
                )
            )
            prop = result.scalar_one_or_none()
            if not prop or not prop.bills:
                continue

            bill = prop.bills[0]
            active_tenants = [t for t in prop.tenants if t.is_active]

            for tenant in active_tenants:
                # Determine recipient
                if channel_enum == NotificationChannel.SMS and tenant.phone:
                    recipient = tenant.phone
                elif channel_enum == NotificationChannel.EMAIL and tenant.email:
                    recipient = tenant.email
                else:
                    continue

                # Format message
                message = template["sms" if channel_enum == NotificationChannel.SMS else "email"].format(
                    address=prop.address,
                    tenant_name=tenant.name,
                    amount=f"{bill.amount_due:.2f}",
                    due_date=bill.due_date.strftime('%B %d, %Y') if bill.due_date else 'N/A',
                    message=""
                )

                # Create notification record
                notification = Notification(
                    tenant_id=tenant.id,
                    property_id=property_id,
                    bill_id=bill.id,
                    channel=channel_enum,
                    recipient=recipient,
                    subject=template["subject"] if channel_enum == NotificationChannel.EMAIL else None,
                    message=message,
                    status=NotificationStatus.PENDING,
                )
                session.add(notification)
                await session.flush()

                # Send notification
                if channel_enum == NotificationChannel.SMS:
                    result = await twilio_service.send_sms(recipient, message)
                else:
                    result = await email_service.send_email(
                        recipient,
                        template["subject"],
                        message
                    )

                # Update status
                if result.success:
                    notification.status = NotificationStatus.SENT
                    notification.external_id = getattr(result, 'message_sid', None) or getattr(result, 'message_id', None)
                    notification.sent_at = datetime.utcnow()
                    sent_count += 1
                else:
                    notification.status = NotificationStatus.FAILED
                    notification.error_message = result.error_message
                    failed_count += 1

        await session.commit()

    return RedirectResponse(url="/notifications", status_code=303)
