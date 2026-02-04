"""Inspections routes"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
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
