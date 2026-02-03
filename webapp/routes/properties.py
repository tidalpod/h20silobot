"""Property management routes"""

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus, Tenant
from webapp.auth.dependencies import get_current_user

router = APIRouter(tags=["properties"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def list_properties(
    request: Request,
    status: str = None,
    search: str = None
):
    """List all properties"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = select(Property).options(
            selectinload(Property.bills),
            selectinload(Property.tenants)
        )

        if search:
            query = query.where(
                Property.address.ilike(f"%{search}%") |
                Property.bsa_account_number.ilike(f"%{search}%")
            )

        result = await session.execute(query.order_by(Property.address))
        all_properties = result.scalars().all()

        # Filter by status if specified
        properties = []
        for prop in all_properties:
            if prop.bills:
                bill_status = prop.bills[0].calculate_status()
            else:
                bill_status = BillStatus.UNKNOWN

            # Compute operational status
            active_tenants = [t for t in prop.tenants if t.is_active]
            is_vacant = len(active_tenants) == 0
            no_license = not prop.has_rental_license
            failed_inspection = prop.section8_inspection_status == 'failed'
            needs_attention = is_vacant or no_license or failed_inspection

            if status:
                if status == "attention" and prop.is_active and needs_attention:
                    properties.append({"property": prop, "status": bill_status})
                elif status == "vacant" and prop.is_active and is_vacant:
                    properties.append({"property": prop, "status": bill_status})
                elif status == "inactive" and not prop.is_active:
                    properties.append({"property": prop, "status": bill_status})
                # Legacy filters (kept for compatibility)
                elif status == "overdue" and bill_status == BillStatus.OVERDUE:
                    properties.append({"property": prop, "status": bill_status})
                elif status == "due_soon" and bill_status == BillStatus.DUE_SOON:
                    properties.append({"property": prop, "status": bill_status})
                elif status == "current" and bill_status == BillStatus.CURRENT:
                    properties.append({"property": prop, "status": bill_status})
                elif status == "paid" and bill_status == BillStatus.PAID:
                    properties.append({"property": prop, "status": bill_status})
            else:
                if prop.is_active:
                    properties.append({"property": prop, "status": bill_status})

    return templates.TemplateResponse(
        "properties/list.html",
        {
            "request": request,
            "user": user,
            "properties": properties,
            "status_filter": status,
            "search": search or "",
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_property_form(request: Request):
    """Show new property form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        "properties/form.html",
        {
            "request": request,
            "user": user,
            "property": None,
            "error": None,
        }
    )


@router.post("/new", response_class=HTMLResponse)
async def create_property(
    request: Request,
    address: str = Form(...),
    bsa_account_number: str = Form(...),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    parcel_number: str = Form(""),
    tenant_name: str = Form(""),
    owner_name: str = Form(""),
    bedrooms: int = Form(None),
    bathrooms: float = Form(None),
    square_feet: int = Form(None),
    year_built: int = Form(None),
    lot_size: str = Form(""),
    property_type: str = Form(""),
    is_vacant: bool = Form(False),
    has_city_certification: bool = Form(False),
    city_certification_date: str = Form(""),
    city_certification_expiry: str = Form(""),
    has_rental_license: bool = Form(False),
    rental_license_number: str = Form(""),
    rental_license_issued: str = Form(""),
    rental_license_expiry: str = Form(""),
    section8_inspection_status: str = Form(""),
    section8_inspection_date: str = Form(""),
    section8_inspection_notes: str = Form("")
):
    """Create a new property"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Check if account number already exists
        result = await session.execute(
            select(Property).where(Property.bsa_account_number == bsa_account_number)
        )
        existing = result.scalar_one_or_none()

        if existing:
            return templates.TemplateResponse(
                "properties/form.html",
                {
                    "request": request,
                    "user": user,
                    "property": None,
                    "error": "A property with this BSA account number already exists",
                },
                status_code=400
            )

        # Helper to parse dates
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    return None
            return None

        # Create property
        prop = Property(
            address=address,
            city=city or None,
            state=state.upper() if state else None,
            zip_code=zip_code or None,
            bsa_account_number=bsa_account_number,
            parcel_number=parcel_number or None,
            tenant_name=tenant_name or None,
            owner_name=owner_name or None,
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            square_feet=square_feet,
            year_built=year_built,
            lot_size=lot_size or None,
            property_type=property_type or None,
            web_user_id=user["id"],
            is_active=True,
            # Occupancy
            is_vacant=is_vacant,
            # City certification
            has_city_certification=has_city_certification,
            city_certification_date=parse_date(city_certification_date),
            city_certification_expiry=parse_date(city_certification_expiry),
            # Rental license
            has_rental_license=has_rental_license,
            rental_license_number=rental_license_number or None,
            rental_license_issued=parse_date(rental_license_issued),
            rental_license_expiry=parse_date(rental_license_expiry),
            # Section 8 inspection
            section8_inspection_status=section8_inspection_status or None,
            section8_inspection_date=parse_date(section8_inspection_date),
            section8_inspection_notes=section8_inspection_notes or None,
        )
        session.add(prop)
        await session.commit()

        return RedirectResponse(url=f"/properties/{prop.id}", status_code=303)


@router.get("/{property_id}", response_class=HTMLResponse)
async def property_detail(request: Request, property_id: int):
    """Show property detail page"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.id == property_id)
            .options(
                selectinload(Property.bills),
                selectinload(Property.tenants).selectinload(Tenant.pha),
                selectinload(Property.taxes)
            )
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # Calculate current status
        current_status = BillStatus.UNKNOWN
        latest_bill = None
        if prop.bills:
            latest_bill = prop.bills[0]
            current_status = latest_bill.calculate_status()

        # Get active tenants
        active_tenants = [t for t in prop.tenants if t.is_active]

    return templates.TemplateResponse(
        "properties/detail.html",
        {
            "request": request,
            "user": user,
            "property": prop,
            "current_status": current_status,
            "latest_bill": latest_bill,
            "active_tenants": active_tenants,
            "bills": prop.bills[:10],  # Last 10 bills
            "today": datetime.now().date(),  # For expiry date comparisons
        }
    )


@router.get("/{property_id}/edit", response_class=HTMLResponse)
async def edit_property_form(request: Request, property_id: int):
    """Show edit property form"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

    return templates.TemplateResponse(
        "properties/form.html",
        {
            "request": request,
            "user": user,
            "property": prop,
            "error": None,
        }
    )


@router.post("/{property_id}/edit", response_class=HTMLResponse)
async def update_property(
    request: Request,
    property_id: int,
    address: str = Form(...),
    bsa_account_number: str = Form(...),
    city: str = Form(""),
    state: str = Form(""),
    zip_code: str = Form(""),
    parcel_number: str = Form(""),
    tenant_name: str = Form(""),
    owner_name: str = Form(""),
    bedrooms: int = Form(None),
    bathrooms: float = Form(None),
    square_feet: int = Form(None),
    year_built: int = Form(None),
    lot_size: str = Form(""),
    property_type: str = Form(""),
    is_active: bool = Form(True),
    is_vacant: bool = Form(False),
    has_city_certification: bool = Form(False),
    city_certification_date: str = Form(""),
    city_certification_expiry: str = Form(""),
    has_rental_license: bool = Form(False),
    rental_license_number: str = Form(""),
    rental_license_issued: str = Form(""),
    rental_license_expiry: str = Form(""),
    section8_inspection_status: str = Form(""),
    section8_inspection_date: str = Form(""),
    section8_inspection_notes: str = Form("")
):
    """Update a property"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # Check for duplicate account number
        if bsa_account_number != prop.bsa_account_number:
            result = await session.execute(
                select(Property).where(Property.bsa_account_number == bsa_account_number)
            )
            existing = result.scalar_one_or_none()
            if existing:
                return templates.TemplateResponse(
                    "properties/form.html",
                    {
                        "request": request,
                        "user": user,
                        "property": prop,
                        "error": "A property with this BSA account number already exists",
                    },
                    status_code=400
                )

        # Helper to parse dates
        def parse_date(date_str):
            if date_str:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d").date()
                except ValueError:
                    return None
            return None

        # Update property
        prop.address = address
        prop.city = city or None
        prop.state = state.upper() if state else None
        prop.zip_code = zip_code or None
        prop.bsa_account_number = bsa_account_number
        prop.parcel_number = parcel_number or None
        prop.tenant_name = tenant_name or None
        prop.owner_name = owner_name or None
        prop.bedrooms = bedrooms
        prop.bathrooms = bathrooms
        prop.square_feet = square_feet
        prop.year_built = year_built
        prop.lot_size = lot_size or None
        prop.property_type = property_type or None
        prop.is_active = is_active
        # Occupancy
        prop.is_vacant = is_vacant
        # City certification
        prop.has_city_certification = has_city_certification
        prop.city_certification_date = parse_date(city_certification_date)
        prop.city_certification_expiry = parse_date(city_certification_expiry)
        # Rental license
        prop.has_rental_license = has_rental_license
        prop.rental_license_number = rental_license_number or None
        prop.rental_license_issued = parse_date(rental_license_issued)
        prop.rental_license_expiry = parse_date(rental_license_expiry)
        # Section 8 inspection
        prop.section8_inspection_status = section8_inspection_status or None
        prop.section8_inspection_date = parse_date(section8_inspection_date)
        prop.section8_inspection_notes = section8_inspection_notes or None

        await session.commit()

        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)


@router.post("/{property_id}/delete")
async def delete_property(request: Request, property_id: int):
    """Delete a property (soft delete by deactivating)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        prop.is_active = False
        await session.commit()

    return RedirectResponse(url="/properties", status_code=303)


@router.post("/{property_id}/delete-permanent")
async def delete_property_permanent(request: Request, property_id: int):
    """Permanently delete a property and all associated data"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # Delete related water bills first (no CASCADE set on this table)
        await session.execute(
            WaterBill.__table__.delete().where(WaterBill.property_id == property_id)
        )

        # Delete related tenants
        await session.execute(
            Tenant.__table__.delete().where(Tenant.property_id == property_id)
        )

        # Now delete the property
        await session.delete(prop)
        await session.commit()

    return RedirectResponse(url="/properties", status_code=303)
