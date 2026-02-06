"""Property management routes"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from decimal import Decimal

from fastapi import APIRouter, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus, Tenant, PropertyPhoto
from webapp.auth.dependencies import get_current_user

# Upload directory - use UPLOAD_PATH env var for Railway volume, fallback to local
# Try env var first, then Railway volume at /app/uploads, then local fallback
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists() else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
UPLOAD_DIR = Path(UPLOAD_BASE) / "properties"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
    bedrooms: str = Form(""),
    bathrooms: str = Form(""),
    square_feet: str = Form(""),
    year_built: str = Form(""),
    lot_size: str = Form(""),
    property_type: str = Form(""),
    is_vacant: str = Form(""),
    has_city_certification: str = Form(""),
    city_certification_date: str = Form(""),
    city_certification_expiry: str = Form(""),
    has_rental_license: str = Form(""),
    rental_license_number: str = Form(""),
    rental_license_issued: str = Form(""),
    rental_license_expiry: str = Form(""),
    section8_inspection_status: str = Form(""),
    section8_inspection_date: str = Form(""),
    section8_inspection_time: str = Form(""),
    section8_inspection_notes: str = Form(""),
    co_mechanical_date: str = Form(""),
    co_mechanical_time: str = Form(""),
    co_electrical_date: str = Form(""),
    co_electrical_time: str = Form(""),
    co_plumbing_date: str = Form(""),
    co_plumbing_time: str = Form(""),
    co_zoning_date: str = Form(""),
    co_zoning_time: str = Form(""),
    co_building_date: str = Form(""),
    co_building_time: str = Form(""),
    rental_inspection_date: str = Form(""),
    rental_inspection_time: str = Form("")
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

        # Helper to parse checkbox values
        def parse_checkbox(val):
            return val in ("on", "true", "1", "yes")

        # Helper to parse int values
        def parse_int(val):
            if val and val.strip():
                try:
                    return int(val)
                except ValueError:
                    return None
            return None

        # Helper to parse float values
        def parse_float(val):
            if val and val.strip():
                try:
                    return float(val)
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
            bedrooms=parse_int(bedrooms),
            bathrooms=parse_float(bathrooms),
            square_feet=parse_int(square_feet),
            year_built=parse_int(year_built),
            lot_size=lot_size or None,
            property_type=property_type or None,
            web_user_id=user["id"],
            is_active=True,
            # Occupancy
            is_vacant=parse_checkbox(is_vacant),
            # City certification
            has_city_certification=parse_checkbox(has_city_certification),
            city_certification_date=parse_date(city_certification_date),
            city_certification_expiry=parse_date(city_certification_expiry),
            # Rental license
            has_rental_license=parse_checkbox(has_rental_license),
            rental_license_number=rental_license_number or None,
            rental_license_issued=parse_date(rental_license_issued),
            rental_license_expiry=parse_date(rental_license_expiry),
            # Section 8 inspection
            section8_inspection_status=section8_inspection_status or None,
            section8_inspection_date=parse_date(section8_inspection_date),
            section8_inspection_time=section8_inspection_time or None,
            section8_inspection_notes=section8_inspection_notes or None,
            # Certificate of Occupancy inspections
            co_mechanical_date=parse_date(co_mechanical_date),
            co_mechanical_time=co_mechanical_time or None,
            co_electrical_date=parse_date(co_electrical_date),
            co_electrical_time=co_electrical_time or None,
            co_plumbing_date=parse_date(co_plumbing_date),
            co_plumbing_time=co_plumbing_time or None,
            co_zoning_date=parse_date(co_zoning_date),
            co_zoning_time=co_zoning_time or None,
            co_building_date=parse_date(co_building_date),
            co_building_time=co_building_time or None,
            # Rental inspection
            rental_inspection_date=parse_date(rental_inspection_date),
            rental_inspection_time=rental_inspection_time or None,
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
            select(Property)
            .where(Property.id == property_id)
            .options(selectinload(Property.photos))
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
    bedrooms: str = Form(""),
    bathrooms: str = Form(""),
    square_feet: str = Form(""),
    year_built: str = Form(""),
    lot_size: str = Form(""),
    property_type: str = Form(""),
    is_active: str = Form(""),
    is_vacant: str = Form(""),
    has_city_certification: str = Form(""),
    city_certification_date: str = Form(""),
    city_certification_expiry: str = Form(""),
    has_rental_license: str = Form(""),
    rental_license_number: str = Form(""),
    rental_license_issued: str = Form(""),
    rental_license_expiry: str = Form(""),
    section8_inspection_status: str = Form(""),
    section8_inspection_date: str = Form(""),
    section8_inspection_time: str = Form(""),
    section8_inspection_notes: str = Form(""),
    co_mechanical_date: str = Form(""),
    co_mechanical_time: str = Form(""),
    co_electrical_date: str = Form(""),
    co_electrical_time: str = Form(""),
    co_plumbing_date: str = Form(""),
    co_plumbing_time: str = Form(""),
    co_zoning_date: str = Form(""),
    co_zoning_time: str = Form(""),
    co_building_date: str = Form(""),
    co_building_time: str = Form(""),
    rental_inspection_date: str = Form(""),
    rental_inspection_time: str = Form(""),
    # Public listing fields
    description: str = Form(""),
    monthly_rent: str = Form(""),
    is_listed: str = Form("")
):
    """Update a property"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Helper to parse dates
    def parse_date(date_str):
        if date_str:
            try:
                return datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    # Helper to parse checkbox values
    def parse_checkbox(val):
        return val in ("on", "true", "1", "yes")

    # Helper to parse int values
    def parse_int(val):
        if val and val.strip():
            try:
                return int(val)
            except ValueError:
                return None
        return None

    # Helper to parse float values
    def parse_float(val):
        if val and val.strip():
            try:
                return float(val)
            except ValueError:
                return None
        return None

    try:
        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .where(Property.id == property_id)
                .options(selectinload(Property.photos))
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

            # Update property
            prop.address = address
            prop.city = city or None
            prop.state = state.upper() if state else None
            prop.zip_code = zip_code or None
            prop.bsa_account_number = bsa_account_number
            prop.parcel_number = parcel_number or None
            prop.tenant_name = tenant_name or None
            prop.owner_name = owner_name or None
            prop.bedrooms = parse_int(bedrooms)
            prop.bathrooms = parse_float(bathrooms)
            prop.square_feet = parse_int(square_feet)
            prop.year_built = parse_int(year_built)
            prop.lot_size = lot_size or None
            prop.property_type = property_type or None
            prop.is_active = parse_checkbox(is_active)
            # Occupancy
            prop.is_vacant = parse_checkbox(is_vacant)
            # City certification
            prop.has_city_certification = parse_checkbox(has_city_certification)
            prop.city_certification_date = parse_date(city_certification_date)
            prop.city_certification_expiry = parse_date(city_certification_expiry)
            # Rental license
            prop.has_rental_license = parse_checkbox(has_rental_license)
            prop.rental_license_number = rental_license_number or None
            prop.rental_license_issued = parse_date(rental_license_issued)
            prop.rental_license_expiry = parse_date(rental_license_expiry)
            # Section 8 inspection
            prop.section8_inspection_status = section8_inspection_status or None
            prop.section8_inspection_date = parse_date(section8_inspection_date)
            prop.section8_inspection_time = section8_inspection_time or None
            prop.section8_inspection_notes = section8_inspection_notes or None
            # Certificate of Occupancy inspections
            prop.co_mechanical_date = parse_date(co_mechanical_date)
            prop.co_mechanical_time = co_mechanical_time or None
            prop.co_electrical_date = parse_date(co_electrical_date)
            prop.co_electrical_time = co_electrical_time or None
            prop.co_plumbing_date = parse_date(co_plumbing_date)
            prop.co_plumbing_time = co_plumbing_time or None
            prop.co_zoning_date = parse_date(co_zoning_date)
            prop.co_zoning_time = co_zoning_time or None
            prop.co_building_date = parse_date(co_building_date)
            prop.co_building_time = co_building_time or None
            # Rental inspection
            prop.rental_inspection_date = parse_date(rental_inspection_date)
            prop.rental_inspection_time = rental_inspection_time or None

            # Public listing fields
            prop.description = description or None
            if monthly_rent:
                try:
                    prop.monthly_rent = Decimal(monthly_rent)
                except:
                    prop.monthly_rent = None
            else:
                prop.monthly_rent = None
            prop.is_listed = is_listed in ("on", "true", "1")

            print(f"[UPDATE] Saving property {property_id}: {address}")

        # Redirect after successful save (session auto-commits on exit)
        return RedirectResponse(url=f"/properties/{property_id}", status_code=303)

    except Exception as e:
        print(f"[UPDATE] ERROR saving property {property_id}: {e}")
        import traceback
        traceback.print_exc()
        return templates.TemplateResponse(
            "properties/form.html",
            {
                "request": request,
                "user": user,
                "property": None,
                "error": f"Error saving property: {str(e)}",
            },
            status_code=500
        )


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


# =============================================================================
# Photo Management
# =============================================================================

@router.post("/{property_id}/photos/upload")
async def upload_photo(
    request: Request,
    property_id: int,
    photo: UploadFile = File(...)
):
    """Upload a photo for a property"""
    user = await get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if photo.content_type not in allowed_types:
        return JSONResponse({"error": "Invalid file type. Use JPG, PNG, WebP, or GIF."}, status_code=400)

    # Validate file size (max 10MB)
    contents = await photo.read()
    if len(contents) > 10 * 1024 * 1024:
        return JSONResponse({"error": "File too large. Max 10MB."}, status_code=400)

    async with get_session() as session:
        # Verify property exists
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()
        if not prop:
            return JSONResponse({"error": "Property not found"}, status_code=404)

        # Generate unique filename
        ext = Path(photo.filename).suffix.lower() or ".jpg"
        filename = f"{property_id}_{uuid.uuid4().hex[:8]}{ext}"
        filepath = UPLOAD_DIR / filename

        # Save file
        with open(filepath, "wb") as f:
            f.write(contents)

        # Get current photo count to determine if this is primary
        result = await session.execute(
            select(PropertyPhoto).where(PropertyPhoto.property_id == property_id)
        )
        existing_photos = result.scalars().all()
        is_primary = len(existing_photos) == 0

        # Create database record
        photo_record = PropertyPhoto(
            property_id=property_id,
            url=f"/uploads/properties/{filename}",
            is_primary=is_primary,
            display_order=len(existing_photos)
        )
        session.add(photo_record)

        # Update featured photo if this is primary
        if is_primary:
            prop.featured_photo_url = f"/uploads/properties/{filename}"

        await session.commit()

        return JSONResponse({
            "success": True,
            "photo_id": photo_record.id,
            "url": photo_record.url
        })


@router.get("/admin/clear-orphaned-photos")
async def clear_orphaned_photos_page(request: Request):
    """Admin page to clear all orphaned photo records"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get all photos
        result = await session.execute(
            select(PropertyPhoto).options(selectinload(PropertyPhoto.property))
        )
        all_photos = result.scalars().all()

        # Check which files exist
        orphaned = []
        for photo in all_photos:
            filename = photo.url.split("/")[-1]
            filepath = UPLOAD_DIR / filename
            if not filepath.exists():
                orphaned.append({
                    "id": photo.id,
                    "property_id": photo.property_id,
                    "url": photo.url,
                    "property_address": photo.property.address if photo.property else "Unknown"
                })

        return JSONResponse({
            "total_photos": len(all_photos),
            "orphaned_count": len(orphaned),
            "orphaned": orphaned[:50]  # Limit to first 50
        })


@router.post("/admin/clear-orphaned-photos")
async def clear_orphaned_photos(request: Request):
    """Delete all orphaned photo records (where file doesn't exist)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Get all photos
        result = await session.execute(select(PropertyPhoto))
        all_photos = result.scalars().all()

        deleted_count = 0
        affected_properties = set()

        for photo in all_photos:
            filename = photo.url.split("/")[-1]
            filepath = UPLOAD_DIR / filename
            if not filepath.exists():
                affected_properties.add(photo.property_id)
                await session.delete(photo)
                deleted_count += 1

        # Clear featured_photo_url for affected properties
        for prop_id in affected_properties:
            result = await session.execute(
                select(Property).where(Property.id == prop_id)
            )
            prop = result.scalar_one_or_none()
            if prop:
                # Check if featured photo still exists
                if prop.featured_photo_url:
                    filename = prop.featured_photo_url.split("/")[-1]
                    filepath = UPLOAD_DIR / filename
                    if not filepath.exists():
                        prop.featured_photo_url = None

        await session.commit()

        return JSONResponse({
            "success": True,
            "deleted_count": deleted_count,
            "affected_properties": len(affected_properties)
        })


@router.post("/{property_id}/photos/clear-all")
async def clear_all_photos(request: Request, property_id: int):
    """Delete all photo records for a property (useful for clearing orphaned records)"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        async with get_session() as session:
            # Get all photos for this property
            result = await session.execute(
                select(PropertyPhoto).where(PropertyPhoto.property_id == property_id)
            )
            photos = result.scalars().all()
            print(f"[CLEAR-ALL] Found {len(photos)} photos for property {property_id}")

            # Delete files from disk (if they exist)
            for photo in photos:
                filename = photo.url.split("/")[-1]
                filepath = UPLOAD_DIR / filename
                if filepath.exists():
                    filepath.unlink()
                    print(f"[CLEAR-ALL] Deleted file: {filepath}")
                # Delete each photo record individually
                await session.delete(photo)

            # Clear featured photo on property
            result = await session.execute(
                select(Property).where(Property.id == property_id)
            )
            prop = result.scalar_one_or_none()
            if prop:
                prop.featured_photo_url = None
                print(f"[CLEAR-ALL] Cleared featured_photo_url for property {property_id}")

        print(f"[CLEAR-ALL] Successfully cleared all photos for property {property_id}")
    except Exception as e:
        print(f"[CLEAR-ALL] ERROR: {e}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

    return RedirectResponse(url=f"/properties/{property_id}/edit", status_code=303)


@router.post("/{property_id}/photos/{photo_id}/delete")
async def delete_photo(request: Request, property_id: int, photo_id: int):
    """Delete a property photo"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PropertyPhoto)
            .where(PropertyPhoto.id == photo_id)
            .where(PropertyPhoto.property_id == property_id)
        )
        photo = result.scalar_one_or_none()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        # Delete file from disk
        filename = photo.url.split("/")[-1]
        filepath = UPLOAD_DIR / filename
        if filepath.exists():
            filepath.unlink()

        was_primary = photo.is_primary

        # Delete from database
        await session.delete(photo)

        # If this was primary, set another photo as primary
        if was_primary:
            result = await session.execute(
                select(PropertyPhoto)
                .where(PropertyPhoto.property_id == property_id)
                .order_by(PropertyPhoto.display_order)
                .limit(1)
            )
            new_primary = result.scalar_one_or_none()
            if new_primary:
                new_primary.is_primary = True
                # Update property featured photo
                result = await session.execute(
                    select(Property).where(Property.id == property_id)
                )
                prop = result.scalar_one_or_none()
                if prop:
                    prop.featured_photo_url = new_primary.url
            else:
                # No photos left, clear featured photo
                result = await session.execute(
                    select(Property).where(Property.id == property_id)
                )
                prop = result.scalar_one_or_none()
                if prop:
                    prop.featured_photo_url = None

        await session.commit()

    return RedirectResponse(url=f"/properties/{property_id}/edit", status_code=303)


@router.post("/{property_id}/photos/{photo_id}/set-primary")
async def set_primary_photo(request: Request, property_id: int, photo_id: int):
    """Set a photo as the primary photo"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        # Unset all other primary photos
        result = await session.execute(
            select(PropertyPhoto).where(PropertyPhoto.property_id == property_id)
        )
        photos = result.scalars().all()
        for p in photos:
            p.is_primary = (p.id == photo_id)

        # Update property featured photo
        result = await session.execute(
            select(PropertyPhoto)
            .where(PropertyPhoto.id == photo_id)
            .where(PropertyPhoto.property_id == property_id)
        )
        photo = result.scalar_one_or_none()
        if photo:
            result = await session.execute(
                select(Property).where(Property.id == property_id)
            )
            prop = result.scalar_one_or_none()
            if prop:
                prop.featured_photo_url = photo.url

        await session.commit()

    return RedirectResponse(url=f"/properties/{property_id}/edit", status_code=303)


@router.post("/{property_id}/photos/{photo_id}/toggle-star")
async def toggle_star_photo(request: Request, property_id: int, photo_id: int):
    """Toggle the starred/featured status of a photo"""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(PropertyPhoto)
            .where(PropertyPhoto.id == photo_id)
            .where(PropertyPhoto.property_id == property_id)
        )
        photo = result.scalar_one_or_none()

        if not photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        # Toggle the starred status
        photo.is_starred = not photo.is_starred

        await session.commit()

    return RedirectResponse(url=f"/properties/{property_id}/edit", status_code=303)


# =============================================================================
# Listing Settings
# =============================================================================

@router.post("/{property_id}/listing")
async def update_listing_settings(
    request: Request,
    property_id: int,
    description: str = Form(""),
    monthly_rent: str = Form(""),
    is_listed: str = Form("")
):
    """Update property listing settings"""
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

        prop.description = description or None
        prop.monthly_rent = Decimal(monthly_rent) if monthly_rent and monthly_rent.strip() else None
        prop.is_listed = is_listed.lower() == "true" if is_listed else False

        await session.commit()

    return RedirectResponse(url=f"/properties/{property_id}/edit", status_code=303)
