"""Dashboard routes"""

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from typing import List

from database.connection import get_session
from database.models import (
    Property, WaterBill, BillStatus, Notification, Tenant,
    WorkOrder, WorkOrderStatus, WorkOrderPriority, LeaseDocument, LeaseStatus,
    Showing, ShowingStatus,
)
from webapp.auth.dependencies import get_current_user

# Canonical entity list
ENTITIES = ["Silo Capital LLC", "Silo Partners LLC", "Homes for America LLC", "Casa Sicura LLC", "Chulo Apartments LLC"]

router = APIRouter(tags=["dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, entity: List[str] = None):
    """Main dashboard page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Parse entity filters from query string (?entity=X&entity=Y)
    selected_entities = request.query_params.getlist("entity") if request.query_params.getlist("entity") else []

    async with get_session() as session:
        # Get all active properties with bills and tenants
        query = (
            select(Property)
            .where(Property.is_active == True)
            .options(
                selectinload(Property.bills),
                selectinload(Property.tenants)
            )
            .order_by(Property.address)
        )
        if selected_entities:
            query = query.where(Property.entity.in_(selected_entities))

        result = await session.execute(query)
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

        # === OUTSTANDING WATER BILLS ===
        outstanding_bills = []

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

            # Water bills - check for outstanding amounts
            if prop.bills:
                latest = prop.bills[0]
                status = latest.calculate_status()
                if latest.amount_due and float(latest.amount_due) > 0:
                    days_overdue = 0
                    if latest.due_date:
                        days_overdue = (datetime.now().date() - latest.due_date).days
                    outstanding_bills.append({
                        "property": prop,
                        "amount": float(latest.amount_due),
                        "due_date": latest.due_date,
                        "days_overdue": days_overdue,
                        "is_overdue": status == BillStatus.OVERDUE
                    })
                    if status == BillStatus.OVERDUE:
                        overdue_bills_count += 1

        # Sort attention items: danger first, then warning
        severity_order = {"danger": 0, "warning": 1}
        attention_items.sort(key=lambda x: severity_order.get(x["severity"], 2))

        # Unique properties needing attention (a property may have multiple issues)
        properties_needing_attention = set()
        for item in attention_items:
            properties_needing_attention.add(item["property"].id)
        needs_attention_count = len(properties_needing_attention)

        # === KPI 4: TENANTS ===
        # When filtering by entity, scope tenants to those properties
        property_ids = [p.id for p in properties] if selected_entities else None
        tenant_query = select(Tenant).where(Tenant.is_active == True)
        if property_ids is not None:
            tenant_query = tenant_query.where(Tenant.property_id.in_(property_ids))
        result = await session.execute(tenant_query)
        all_tenants = result.scalars().all()
        total_tenants = len(all_tenants)
        section8_tenants = sum(1 for t in all_tenants if t.is_section8)

        # === KPI 5: TOTAL RENT ===
        # Match the exact logic from properties/list.html template
        # Iterate through properties and get rent from primary/first tenant
        total_rent = 0
        total_section8_rent = 0
        total_regular_rent = 0

        for prop in properties:
            active_tenants = [t for t in prop.tenants if t.is_active]
            if active_tenants:
                # Get primary tenant or first active tenant
                primary = next((t for t in active_tenants if t.is_primary), None)
                rent_tenant = primary if primary else active_tenants[0]

                if rent_tenant.is_section8 and (rent_tenant.voucher_amount or rent_tenant.tenant_portion):
                    # Section 8: voucher_amount + tenant_portion
                    voucher = float(rent_tenant.voucher_amount or 0)
                    portion = float(rent_tenant.tenant_portion or 0)
                    total_rent += voucher + portion
                    total_section8_rent += voucher + portion
                elif rent_tenant.current_rent:
                    # Regular tenant: current_rent
                    total_rent += float(rent_tenant.current_rent)
                    total_regular_rent += float(rent_tenant.current_rent)

        # === RECENT ACTIVITY (Notifications) ===
        result = await session.execute(
            select(Notification)
            .options(selectinload(Notification.property))
            .order_by(Notification.created_at.desc())
            .limit(5)
        )
        recent_notifications = result.scalars().all()

        # === UPCOMING RECERTIFICATIONS ===
        recert_query = (
            select(Tenant)
            .where(Tenant.is_active == True)
            .where(Tenant.lease_start_date != None)
            .options(selectinload(Tenant.property_ref))
            .order_by(Tenant.lease_start_date)
        )
        if property_ids is not None:
            recert_query = recert_query.where(Tenant.property_id.in_(property_ids))
        result = await session.execute(recert_query)
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

        # === UPCOMING INSPECTIONS ===
        today = datetime.now().date()
        upcoming_inspections = []

        for prop in properties:
            # CO Inspections
            co_inspections = [
                ("Mechanical", "⚙️", prop.co_mechanical_date, prop.co_mechanical_time),
                ("Electrical", "⚡", prop.co_electrical_date, prop.co_electrical_time),
                ("Plumbing", "🔧", prop.co_plumbing_date, prop.co_plumbing_time),
                ("Zoning", "📐", prop.co_zoning_date, prop.co_zoning_time),
                ("Building", "🏢", prop.co_building_date, prop.co_building_time),
            ]

            for insp_name, icon, insp_date, insp_time in co_inspections:
                if insp_date and insp_date >= today:
                    days_until = (insp_date - today).days
                    if days_until <= 30:  # Show inspections within 30 days
                        upcoming_inspections.append({
                            "property": prop,
                            "type": f"CO {insp_name}",
                            "icon": icon,
                            "date": insp_date,
                            "time": insp_time,
                            "days_until": days_until
                        })

            # Rental Inspection
            if prop.rental_inspection_date and prop.rental_inspection_date >= today:
                days_until = (prop.rental_inspection_date - today).days
                if days_until <= 30:
                    upcoming_inspections.append({
                        "property": prop,
                        "type": "Rental Inspection",
                        "icon": "🏠",
                        "date": prop.rental_inspection_date,
                        "time": prop.rental_inspection_time,
                        "days_until": days_until
                    })

            # Section 8 Inspection
            if prop.section8_inspection_date and prop.section8_inspection_date >= today:
                if prop.section8_inspection_status in ('scheduled', 'pending', 'reinspection'):
                    days_until = (prop.section8_inspection_date - today).days
                    if days_until <= 30:
                        upcoming_inspections.append({
                            "property": prop,
                            "type": "Section 8 Inspection",
                            "icon": "🔍",
                            "date": prop.section8_inspection_date,
                            "time": prop.section8_inspection_time,
                            "days_until": days_until
                        })

        # Sort by date
        upcoming_inspections.sort(key=lambda x: x["date"])

        # Sort outstanding bills: overdue first, then by amount descending
        outstanding_bills.sort(key=lambda x: (not x["is_overdue"], -x["amount"]))

        # Calculate total outstanding
        total_outstanding = sum(b["amount"] for b in outstanding_bills)

        # === WORK ORDERS ===
        wo_query = select(func.count(WorkOrder.id)).where(
            WorkOrder.status.in_([WorkOrderStatus.NEW, WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS])
        )
        if property_ids is not None:
            wo_query = wo_query.where(WorkOrder.property_id.in_(property_ids))
        wo_open_result = await session.execute(wo_query)
        open_work_orders = wo_open_result.scalar() or 0

        wo_em_query = select(func.count(WorkOrder.id)).where(
            WorkOrder.status.in_([WorkOrderStatus.NEW, WorkOrderStatus.ASSIGNED, WorkOrderStatus.IN_PROGRESS]),
            WorkOrder.priority == WorkOrderPriority.EMERGENCY,
        )
        if property_ids is not None:
            wo_em_query = wo_em_query.where(WorkOrder.property_id.in_(property_ids))
        wo_emergency_result = await session.execute(wo_em_query)
        emergency_work_orders = wo_emergency_result.scalar() or 0

        # === UPCOMING SHOWINGS ===
        showing_threshold = today + timedelta(days=7)
        showing_query = select(func.count(Showing.id)).where(
            Showing.status.in_([ShowingStatus.SCHEDULED.value, ShowingStatus.CONFIRMED.value]),
            Showing.scheduled_date >= today,
            Showing.scheduled_date <= showing_threshold,
        )
        if property_ids is not None:
            showing_query = showing_query.where(Showing.property_id.in_(property_ids))
        upcoming_showings_result = await session.execute(showing_query)
        upcoming_showings = upcoming_showings_result.scalar() or 0

        # === EXPIRING LEASES ===
        today = datetime.now().date()
        threshold_30 = today + timedelta(days=30)
        lease_query = (
            select(LeaseDocument)
            .where(
                LeaseDocument.status == LeaseStatus.ACTIVE,
                LeaseDocument.lease_end != None,
                LeaseDocument.lease_end <= threshold_30,
                LeaseDocument.lease_end >= today,
            )
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
            .order_by(LeaseDocument.lease_end)
        )
        if property_ids is not None:
            lease_query = lease_query.where(LeaseDocument.property_id.in_(property_ids))
        lease_result = await session.execute(lease_query)
        expiring_leases = lease_result.scalars().all()

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
            "total_section8_rent": total_section8_rent,
            "total_regular_rent": total_regular_rent,
            # Portfolio snapshot
            "section8_properties": section8_properties,
            "pending_inspections": pending_inspections,
            "overdue_bills_count": overdue_bills_count,
            # Recent activity
            "recent_notifications": recent_notifications,
            # Recerts
            "upcoming_recerts": upcoming_recerts[:5],
            # Inspections
            "upcoming_inspections": upcoming_inspections[:5],
            # Outstanding bills
            "outstanding_bills": outstanding_bills[:5],
            "total_outstanding": total_outstanding,
            # State
            "all_caught_up": all_caught_up,
            # Work Orders
            "open_work_orders": open_work_orders,
            "emergency_work_orders": emergency_work_orders,
            # Showings
            "upcoming_showings": upcoming_showings,
            # Expiring Leases
            "expiring_leases": expiring_leases[:5],
            "today": datetime.now().date(),
            # Entity filter
            "entities": ENTITIES,
            "selected_entities": selected_entities,
        }
    )
