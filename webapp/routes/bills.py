"""Bill management routes"""

from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["bills"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_bills(request: Request, property_id: int = None):
    """List all bills or bills for a specific property"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(WaterBill)
            .options(selectinload(WaterBill.property))
        )

        if property_id:
            query = query.where(WaterBill.property_id == property_id)

        result = await session.execute(
            query.order_by(WaterBill.scraped_at.desc()).limit(100)
        )
        bills = result.scalars().all()

        # Get properties for filter
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .order_by(Property.address)
        )
        properties = result.scalars().all()

    return templates.TemplateResponse(
        "bills/list.html",
        {
            "request": request,
            "user": user,
            "bills": bills,
            "properties": properties,
            "property_id": property_id,
        }
    )


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
