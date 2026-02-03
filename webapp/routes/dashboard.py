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
        # Get all active properties with bills and tenants
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .options(
                selectinload(Property.bills),
                selectinload(Property.tenants)
            )
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        # === KPI 1: PROPERTIES ===
        total_properties = len(properties)
        vacant_count = 0
        occupied_count = 0

        # === KPI 2: NEEDS ATTENTION ===
        attention_items = []  # Priority queue items

        # === KPI 3: COMPLIANCE ===
        licensed_count = 0
        missing_license_count = 0

        # === Tracking for portfolio snapshot ===
        section8_properties = 0
        pending_inspections = 0
        overdue_bills_count = 0

        for prop in properties:
            # Get active tenants for this property
            active_tenants = [t for t in prop.tenants if t.is_active]
            has_section8 = any(t.is_section8 for t in active_tenants)

            if has_section8:
                section8_properties += 1

            # Occupancy
            if len(active_tenants) == 0:
                vacant_count += 1
                attention_items.append({
                    "property": prop,
                    "issue": "Vacant",
                    "severity": "warning",  # yellow
                    "icon": "🔑"
                })
            else:
                occupied_count += 1

            # License compliance
            if prop.has_rental_license:
                licensed_count += 1
            else:
                missing_license_count += 1
                attention_items.append({
                    "property": prop,
                    "issue": "No Rental License",
                    "severity": "danger",  # red
                    "icon": "📜"
                })

            # Section 8 inspection status
            if prop.section8_inspection_status == 'failed':
                attention_items.append({
                    "property": prop,
                    "issue": "Section 8 inspection failed",
                    "severity": "danger",
                    "icon": "🔍"
                })
            elif prop.section8_inspection_status in ('pending', 'scheduled', 'reinspection'):
                pending_inspections += 1

            # Overdue utilities
            if prop.bills:
                latest = prop.bills[0]
                status = latest.calculate_status()
                if status == BillStatus.OVERDUE:
                    overdue_bills_count += 1
                    attention_items.append({
                        "property": prop,
                        "issue": f"Water bill overdue (${latest.amount_due:.0f})",
                        "severity": "danger",
                        "icon": "💧"
                    })

        # Sort attention items: danger first, then warning
        severity_order = {"danger": 0, "warning": 1}
        attention_items.sort(key=lambda x: severity_order.get(x["severity"], 2))

        # Unique properties needing attention (a property may have multiple issues)
        properties_needing_attention = set()
        for item in attention_items:
            properties_needing_attention.add(item["property"].id)
        needs_attention_count = len(properties_needing_attention)

        # === KPI 4: TENANTS ===
        result = await session.execute(
            select(Tenant).where(Tenant.is_active == True)
        )
        all_tenants = result.scalars().all()
        total_tenants = len(all_tenants)
        section8_tenants = sum(1 for t in all_tenants if t.is_section8)

        # === KPI 5: TOTAL RENT ===
        total_rent = sum(float(t.current_rent or 0) for t in all_tenants)
        total_tenant_portion = sum(float(t.tenant_portion or 0) for t in all_tenants if t.is_section8)
        # Voucher rent = current_rent - tenant_portion for Section 8 tenants
        total_voucher_rent = sum(
            float(t.current_rent or 0) - float(t.tenant_portion or 0)
            for t in all_tenants if t.is_section8
        )
        market_rent = sum(float(t.current_rent or 0) for t in all_tenants if not t.is_section8)

        # === RECENT ACTIVITY (Notifications) ===
        result = await session.execute(
            select(Notification)
            .options(selectinload(Notification.property))
            .order_by(Notification.created_at.desc())
            .limit(5)
        )
        recent_notifications = result.scalars().all()

        # === UPCOMING RECERTIFICATIONS ===
        result = await session.execute(
            select(Tenant)
            .where(Tenant.is_active == True)
            .where(Tenant.lease_start_date != None)
            .options(selectinload(Tenant.property_ref))
            .order_by(Tenant.lease_start_date)
        )
        tenants_with_lease = result.scalars().all()

        upcoming_recerts = []
        for tenant in tenants_with_lease:
            if tenant.recert_eligible_date:
                days = tenant.days_until_recert
                if days is not None and days <= 60:
                    upcoming_recerts.append({
                        "tenant": tenant,
                        "property": tenant.property_ref,
                        "recert_date": tenant.recert_eligible_date,
                        "days_until": days
                    })

        upcoming_recerts.sort(key=lambda x: x["recert_date"])

        # === DETERMINE "ALL CAUGHT UP" STATE ===
        all_caught_up = (
            needs_attention_count == 0 and
            overdue_bills_count == 0 and
            missing_license_count == 0
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            # KPI 1: Properties
            "total_properties": total_properties,
            "vacant_count": vacant_count,
            "occupied_count": occupied_count,
            # KPI 2: Needs Attention
            "needs_attention_count": needs_attention_count,
            "attention_items": attention_items[:5],  # Top 5 for priority queue
            # KPI 3: Compliance
            "licensed_count": licensed_count,
            "missing_license_count": missing_license_count,
            # KPI 4: Tenants
            "total_tenants": total_tenants,
            "section8_tenants": section8_tenants,
            # KPI 5: Total Rent
            "total_rent": total_rent,
            "total_voucher_rent": total_voucher_rent,
            "total_tenant_portion": total_tenant_portion,
            "market_rent": market_rent,
            # Portfolio snapshot
            "section8_properties": section8_properties,
            "pending_inspections": pending_inspections,
            "overdue_bills_count": overdue_bills_count,
            # Recent activity
            "recent_notifications": recent_notifications,
            # Recerts
            "upcoming_recerts": upcoming_recerts[:5],
            # State
            "all_caught_up": all_caught_up,
        }
    )
