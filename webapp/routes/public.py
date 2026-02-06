"""Public-facing property listing pages"""

from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, PropertyPhoto, Tenant

router = APIRouter(tags=["public"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/listings", response_class=HTMLResponse)
async def public_listings(request: Request, available_only: bool = False):
    """Public property listings page"""
    async with get_session() as session:
        query = (
            select(Property)
            .where(Property.is_active == True)
            .options(
                selectinload(Property.photos),
                selectinload(Property.tenants)
            )
            .order_by(Property.is_vacant.desc(), Property.address)
        )

        # Optionally filter to only vacant/available properties
        if available_only:
            query = query.where(Property.is_vacant == True)

        result = await session.execute(query)
        properties = result.scalars().all()

        # Build listing data with rent info
        listings = []
        for prop in properties:
            # Get rent from tenant or monthly_rent field
            rent = None
            if prop.monthly_rent:
                rent = float(prop.monthly_rent)
            else:
                active_tenants = [t for t in prop.tenants if t.is_active]
                if active_tenants:
                    tenant = active_tenants[0]
                    if tenant.is_section8 and tenant.voucher_amount:
                        rent = float(tenant.voucher_amount) + float(tenant.tenant_portion or 0)
                    elif tenant.current_rent:
                        rent = float(tenant.current_rent)

            # Get primary photo
            primary_photo = None
            if prop.featured_photo_url:
                primary_photo = prop.featured_photo_url
            elif prop.photos:
                primary = next((p for p in prop.photos if p.is_primary), None)
                primary_photo = primary.url if primary else prop.photos[0].url if prop.photos else None

            listings.append({
                "property": prop,
                "rent": rent,
                "photo": primary_photo,
                "photo_count": len(prop.photos)
            })

    return templates.TemplateResponse(
        "public/listings.html",
        {
            "request": request,
            "listings": listings,
            "available_only": available_only,
            "total_count": len(listings),
            "available_count": sum(1 for l in listings if l["property"].is_vacant)
        }
    )


@router.get("/listings/{property_id}", response_class=HTMLResponse)
async def public_property_detail(request: Request, property_id: int):
    """Public property detail page"""
    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.id == property_id)
            .where(Property.is_active == True)
            .options(
                selectinload(Property.photos),
                selectinload(Property.tenants)
            )
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        # Get rent
        rent = None
        if prop.monthly_rent:
            rent = float(prop.monthly_rent)
        else:
            active_tenants = [t for t in prop.tenants if t.is_active]
            if active_tenants:
                tenant = active_tenants[0]
                if tenant.is_section8 and tenant.voucher_amount:
                    rent = float(tenant.voucher_amount) + float(tenant.tenant_portion or 0)
                elif tenant.current_rent:
                    rent = float(tenant.current_rent)

        # Sort photos by display_order
        photos = sorted(prop.photos, key=lambda p: (not p.is_primary, p.display_order))

    return templates.TemplateResponse(
        "public/property_detail.html",
        {
            "request": request,
            "property": prop,
            "rent": rent,
            "photos": photos
        }
    )
