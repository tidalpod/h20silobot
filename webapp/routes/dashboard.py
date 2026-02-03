"""Dashboard routes"""

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus, Notification, Tenant
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get all properties with their latest bills
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .options(selectinload(Property.bills))
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        # Calculate dashboard stats
        total_properties = len(properties)
        overdue_bills = []
        due_soon_bills = []
        total_overdue_amount = 0
        total_due_soon_amount = 0

        for prop in properties:
            if prop.bills:
                latest = prop.bills[0]
                status = latest.calculate_status()
                if status == BillStatus.OVERDUE:
                    overdue_bills.append({"property": prop, "bill": latest})
                    total_overdue_amount += float(latest.amount_due or 0)
                elif status == BillStatus.DUE_SOON:
                    due_soon_bills.append({"property": prop, "bill": latest})
                    total_due_soon_amount += float(latest.amount_due or 0)

        # Get recent notifications
        result = await session.execute(
            select(Notification)
            .order_by(Notification.created_at.desc())
            .limit(5)
        )
        recent_notifications = result.scalars().all()

        # Get tenant count
        result = await session.execute(
            select(func.count(Tenant.id)).where(Tenant.is_active == True)
        )
        total_tenants = result.scalar() or 0

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "total_properties": total_properties,
            "overdue_count": len(overdue_bills),
            "overdue_bills": overdue_bills,
            "total_overdue_amount": total_overdue_amount,
            "due_soon_count": len(due_soon_bills),
            "due_soon_bills": due_soon_bills,
            "total_due_soon_amount": total_due_soon_amount,
            "total_tenants": total_tenants,
            "recent_notifications": recent_notifications,
        }
    )
