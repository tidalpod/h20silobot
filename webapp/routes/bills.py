"""Bill management routes"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus, Tenant, BillAlertSettings
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["bills"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_bills(request: Request, property_id: int = None, show_all: str = None):
    """List latest bill per property, or all bills for a specific property"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        if property_id or show_all:
            # Show all bills when filtering by property or explicitly requested
            query = (
                select(WaterBill)
                .options(
                    selectinload(WaterBill.property).selectinload(Property.tenants),
                )
            )
            if property_id:
                query = query.where(WaterBill.property_id == property_id)
            result = await session.execute(
                query.order_by(WaterBill.scraped_at.desc()).limit(100)
            )
            bills = result.scalars().all()
        else:
            # Default: show only the latest bill per property
            latest_subq = (
                select(
                    WaterBill.property_id,
                    func.max(WaterBill.scraped_at).label("max_scraped")
                )
                .group_by(WaterBill.property_id)
                .subquery()
            )
            result = await session.execute(
                select(WaterBill)
                .join(
                    latest_subq,
                    (WaterBill.property_id == latest_subq.c.property_id) &
                    (WaterBill.scraped_at == latest_subq.c.max_scraped)
                )
                .options(
                    selectinload(WaterBill.property).selectinload(Property.tenants),
                )
                .order_by(WaterBill.scraped_at.desc())
            )
            bills = result.scalars().all()

        # Get properties for filter
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        # Load bill alert settings (single-row config)
        alert_result = await session.execute(select(BillAlertSettings).limit(1))
        alert_settings = alert_result.scalar_one_or_none()

    return templates.TemplateResponse(
        "bills/list.html",
        {
            "request": request,
            "user": user,
            "bills": bills,
            "properties": properties,
            "property_id": property_id,
            "show_all": show_all,
            "now": datetime.utcnow(),
            "alert_settings": alert_settings,
        }
    )


@router.post("/alert-settings")
async def save_alert_settings(request: Request):
    """Save bill alert automation settings"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    enabled = form.get("enabled") == "on"
    threshold = float(form.get("threshold_amount", 200))
    notify_sms = form.get("notify_sms") == "on"
    notify_email = form.get("notify_email") == "on"
    renotify_increment = float(form.get("renotify_increment", 50))

    async with get_session() as session:
        result = await session.execute(select(BillAlertSettings).limit(1))
        settings = result.scalar_one_or_none()

        if settings:
            settings.enabled = enabled
            settings.threshold_amount = threshold
            settings.notify_sms = notify_sms
            settings.notify_email = notify_email
            settings.renotify_increment = renotify_increment
            settings.updated_at = datetime.utcnow()
        else:
            settings = BillAlertSettings(
                enabled=enabled,
                threshold_amount=threshold,
                notify_sms=notify_sms,
                notify_email=notify_email,
                renotify_increment=renotify_increment,
            )
            session.add(settings)

        await session.commit()

    return RedirectResponse(url="/bills", status_code=303)


@router.get("/refresh", response_class=HTMLResponse)
async def refresh_bills_page(request: Request):
    """Show bill refresh status page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get properties for selection
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .order_by(Property.address)
        )
        properties = result.scalars().all()

    return templates.TemplateResponse(
        "bills/refresh.html",
        {
            "request": request,
            "user": user,
            "properties": properties,
        }
    )
