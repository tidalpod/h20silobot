"""Inspections routes"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property
from webapp.auth.dependencies import get_current_user

router = APIRouter(prefix="/inspections", tags=["inspections"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string to date object"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


@router.get("/", response_class=HTMLResponse)
async def inspections_list(request: Request):
    """List all upcoming inspections"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    today = datetime.now().date()

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        # Collect all inspections
        co_inspections = []
        rental_inspections = []
        section8_inspections = []

        for prop in properties:
            # CO Inspections
            co_types = [
                ("Mechanical", "co_mechanical_date", "co_mechanical_time", "⚙️"),
                ("Electrical", "co_electrical_date", "co_electrical_time", "⚡"),
                ("Plumbing", "co_plumbing_date", "co_plumbing_time", "🔧"),
                ("Zoning", "co_zoning_date", "co_zoning_time", "📐"),
                ("Building", "co_building_date", "co_building_time", "🏢"),
            ]

            for insp_name, date_field, time_field, icon in co_types:
                insp_date = getattr(prop, date_field)
                insp_time = getattr(prop, time_field)
                if insp_date:
                    days_until = (insp_date - today).days
                    co_inspections.append({
                        "property": prop,
                        "type": insp_name,
                        "icon": icon,
                        "date": insp_date,
                        "time": insp_time,
                        "days_until": days_until,
                        "is_past": days_until < 0
                    })

            # Rental Inspection
            if prop.rental_inspection_date:
                days_until = (prop.rental_inspection_date - today).days
                rental_inspections.append({
                    "property": prop,
                    "date": prop.rental_inspection_date,
                    "time": prop.rental_inspection_time,
                    "days_until": days_until,
                    "is_past": days_until < 0
                })

            # Section 8 Inspection
            if prop.section8_inspection_date and prop.section8_inspection_status in ('scheduled', 'pending', 'reinspection'):
                days_until = (prop.section8_inspection_date - today).days
                section8_inspections.append({
                    "property": prop,
                    "status": prop.section8_inspection_status,
                    "date": prop.section8_inspection_date,
                    "time": prop.section8_inspection_time,
                    "notes": prop.section8_inspection_notes,
                    "days_until": days_until,
                    "is_past": days_until < 0
                })

        # Sort by date
        co_inspections.sort(key=lambda x: x["date"])
        rental_inspections.sort(key=lambda x: x["date"])
        section8_inspections.sort(key=lambda x: x["date"])

        # Separate upcoming and past
        upcoming_co = [i for i in co_inspections if not i["is_past"]]
        past_co = [i for i in co_inspections if i["is_past"]]

        upcoming_rental = [i for i in rental_inspections if not i["is_past"]]
        past_rental = [i for i in rental_inspections if i["is_past"]]

        upcoming_section8 = [i for i in section8_inspections if not i["is_past"]]
        past_section8 = [i for i in section8_inspections if i["is_past"]]

    return templates.TemplateResponse(
        "inspections/list.html",
        {
            "request": request,
            "user": user,
            "today": today,
            # All properties for scheduling new inspections
            "properties": properties,
            # CO Inspections
            "upcoming_co": upcoming_co,
            "past_co": past_co[:10],  # Last 10 past
            # Rental Inspections
            "upcoming_rental": upcoming_rental,
            "past_rental": past_rental[:10],
            # Section 8 Inspections
            "upcoming_section8": upcoming_section8,
            "past_section8": past_section8[:10],
            # Counts
            "total_upcoming": len(upcoming_co) + len(upcoming_rental) + len(upcoming_section8),
        }
    )


@router.post("/co/update")
async def update_co_inspection(
    request: Request,
    property_id: int = Form(...),
    inspection_type: str = Form(...),
    date: str = Form(""),
    time: str = Form("")
):
    """Update a CO inspection date/time"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Map inspection type to field names
    field_map = {
        "mechanical": ("co_mechanical_date", "co_mechanical_time"),
        "electrical": ("co_electrical_date", "co_electrical_time"),
        "plumbing": ("co_plumbing_date", "co_plumbing_time"),
        "zoning": ("co_zoning_date", "co_zoning_time"),
        "building": ("co_building_date", "co_building_time"),
    }

    if inspection_type.lower() not in field_map:
        return RedirectResponse(url="/inspections", status_code=303)

    date_field, time_field = field_map[inspection_type.lower()]

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            setattr(prop, date_field, parse_date(date))
            setattr(prop, time_field, time if time else None)
            await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/rental/update")
async def update_rental_inspection(
    request: Request,
    property_id: int = Form(...),
    date: str = Form(""),
    time: str = Form("")
):
    """Update a rental inspection date/time"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            prop.rental_inspection_date = parse_date(date)
            prop.rental_inspection_time = time if time else None
            await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/section8/update")
async def update_section8_inspection(
    request: Request,
    property_id: int = Form(...),
    date: str = Form(""),
    time: str = Form(""),
    status: str = Form("scheduled"),
    notes: str = Form("")
):
    """Update a Section 8 inspection"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            prop.section8_inspection_date = parse_date(date)
            prop.section8_inspection_time = time if time else None
            prop.section8_inspection_status = status if status else None
            prop.section8_inspection_notes = notes if notes else None
            await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)


@router.post("/delete")
async def delete_inspection(
    request: Request,
    property_id: int = Form(...),
    inspection_category: str = Form(...),
    inspection_type: str = Form("")
):
    """Clear an inspection date (delete)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if prop:
            if inspection_category == "co":
                field_map = {
                    "mechanical": ("co_mechanical_date", "co_mechanical_time"),
                    "electrical": ("co_electrical_date", "co_electrical_time"),
                    "plumbing": ("co_plumbing_date", "co_plumbing_time"),
                    "zoning": ("co_zoning_date", "co_zoning_time"),
                    "building": ("co_building_date", "co_building_time"),
                }
                if inspection_type.lower() in field_map:
                    date_field, time_field = field_map[inspection_type.lower()]
                    setattr(prop, date_field, None)
                    setattr(prop, time_field, None)
            elif inspection_category == "rental":
                prop.rental_inspection_date = None
                prop.rental_inspection_time = None
            elif inspection_category == "section8":
                prop.section8_inspection_date = None
                prop.section8_inspection_time = None
                prop.section8_inspection_status = None
                prop.section8_inspection_notes = None
            await session.commit()

    return RedirectResponse(url="/inspections", status_code=303)
