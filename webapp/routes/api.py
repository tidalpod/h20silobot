"""JSON API routes for HTMX and programmatic access"""

import logging
import re
from datetime import datetime
from typing import List

import aiohttp
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus, Tenant, WorkOrder, SMSMessage, MessageDirection

router = APIRouter(tags=["api"])
logger = logging.getLogger(__name__)


@router.get("/properties")
async def api_list_properties(request: Request):
    """Get all properties as JSON"""
    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .options(selectinload(Property.bills))
            .order_by(Property.address)
        )
        properties = result.scalars().all()

        return [
            {
                "id": prop.id,
                "address": prop.address,
                "bsa_account_number": prop.bsa_account_number,
                "status": prop.bills[0].calculate_status().value if prop.bills else "unknown",
                "amount_due": float(prop.bills[0].amount_due) if prop.bills else 0,
                "due_date": prop.bills[0].due_date.isoformat() if prop.bills and prop.bills[0].due_date else None,
            }
            for prop in properties
        ]


@router.get("/properties/{property_id}")
async def api_get_property(property_id: int):
    """Get property details as JSON"""
    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.id == property_id)
            .options(
                selectinload(Property.bills),
                selectinload(Property.tenants)
            )
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        latest_bill = prop.bills[0] if prop.bills else None

        return {
            "id": prop.id,
            "address": prop.address,
            "bsa_account_number": prop.bsa_account_number,
            "parcel_number": prop.parcel_number,
            "owner_name": prop.owner_name,
            "tenant_name": prop.tenant_name,
            "is_active": prop.is_active,
            "latest_bill": {
                "amount_due": float(latest_bill.amount_due) if latest_bill else None,
                "due_date": latest_bill.due_date.isoformat() if latest_bill and latest_bill.due_date else None,
                "status": latest_bill.calculate_status().value if latest_bill else "unknown",
            } if latest_bill else None,
            "tenants": [
                {
                    "id": t.id,
                    "name": t.name,
                    "phone": t.phone,
                    "email": t.email,
                    "is_primary": t.is_primary,
                    "is_active": t.is_active,
                }
                for t in prop.tenants
            ],
        }


@router.get("/properties/{property_id}/tenants")
async def api_get_property_tenants(property_id: int):
    """Get tenants for a property as JSON"""
    async with get_session() as session:
        result = await session.execute(
            select(Tenant)
            .where(Tenant.property_id == property_id, Tenant.is_active == True)
            .order_by(Tenant.is_primary.desc(), Tenant.name)
        )
        tenants = result.scalars().all()

        return [
            {
                "id": t.id,
                "name": t.name,
                "phone": t.phone,
                "email": t.email,
                "is_primary": t.is_primary,
            }
            for t in tenants
        ]


@router.post("/properties/{property_id}/refresh")
async def api_refresh_property(property_id: int):
    """Refresh bill data for a specific property (runs synchronously)"""
    from scraper.bsa_scraper import BSAScraper

    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        logger.info(f"Refreshing bills for property: {prop.address} (city: {prop.city})")

        try:
            # Get the correct BSA UID for this property's city
            municipality_uid = BSAScraper.get_uid_for_city(prop.city)
            logger.info(f"Using BSA municipality UID: {municipality_uid}")

            async with BSAScraper(municipality_uid=municipality_uid) as scraper:
                bill_data = None

                # First try by account number
                if prop.bsa_account_number:
                    logger.info(f"Searching by account: {prop.bsa_account_number}")
                    bill_data = await scraper.search_by_account(prop.bsa_account_number)

                # Fall back to address search
                if not bill_data:
                    street_address = prop.address.split(',')[0].strip()
                    logger.info(f"Trying address search: {street_address}")
                    bill_data = await scraper.search_by_address(street_address)

                if bill_data:
                    # Create new bill record
                    bill = WaterBill(
                        property_id=prop.id,
                        amount_due=bill_data.amount_due,
                        previous_balance=bill_data.previous_balance,
                        current_charges=bill_data.current_charges,
                        late_fees=bill_data.late_fees,
                        payments_received=bill_data.payments_received,
                        statement_date=bill_data.statement_date,
                        due_date=bill_data.due_date,
                        water_usage_gallons=bill_data.water_usage,
                        raw_data=str(bill_data.raw_data) if bill_data.raw_data else None,
                    )
                    bill.status = bill.calculate_status()
                    session.add(bill)

                    # Update property info
                    if bill_data.owner_name and not prop.owner_name:
                        prop.owner_name = bill_data.owner_name
                    if hasattr(bill_data, 'parcel_number') and bill_data.parcel_number and not prop.parcel_number:
                        prop.parcel_number = bill_data.parcel_number
                    if bill_data.account_number and bill_data.account_number != prop.bsa_account_number:
                        prop.bsa_account_number = bill_data.account_number

                    await session.commit()
                    logger.info(f"Successfully saved bill for {prop.address}: ${bill_data.amount_due}")
                    return {"status": "success", "message": f"Found bill: ${bill_data.amount_due}"}
                else:
                    logger.warning(f"No bill data found for {prop.address}")
                    return {"status": "not_found", "message": "No bill data found on BSA Online"}

        except Exception as e:
            logger.error(f"Error refreshing {prop.address}: {e}")
            return {"status": "error", "message": str(e)}


@router.post("/refresh-bills")
async def api_refresh_all_bills(background_tasks: BackgroundTasks):
    """Trigger bill refresh for all active properties"""
    background_tasks.add_task(refresh_all_properties)
    return {"status": "started", "message": "Refreshing all bills in background"}


@router.get("/dashboard/stats")
async def api_dashboard_stats():
    """Get dashboard statistics as JSON"""
    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.is_active == True)
            .options(selectinload(Property.bills))
        )
        properties = result.scalars().all()

        total = len(properties)
        overdue = 0
        due_soon = 0
        total_overdue_amount = 0
        total_due_soon_amount = 0

        for prop in properties:
            if prop.bills:
                status = prop.bills[0].calculate_status()
                amount = float(prop.bills[0].amount_due or 0)
                if status == BillStatus.OVERDUE:
                    overdue += 1
                    total_overdue_amount += amount
                elif status == BillStatus.DUE_SOON:
                    due_soon += 1
                    total_due_soon_amount += amount

        return {
            "total_properties": total,
            "overdue_count": overdue,
            "due_soon_count": due_soon,
            "total_overdue_amount": total_overdue_amount,
            "total_due_soon_amount": total_due_soon_amount,
        }


async def refresh_single_property(property_id: int):
    """Background task to refresh a single property's bills"""
    try:
        from scraper.bsa_scraper import BSAScraper

        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.id == property_id)
            )
            prop = result.scalar_one_or_none()

            if not prop:
                logger.error(f"Property {property_id} not found for refresh")
                return

            logger.info(f"Refreshing bills for property: {prop.address}")

            async with BSAScraper() as scraper:
                bill_data = None

                # First try by account number if we have one
                if prop.bsa_account_number:
                    logger.info(f"Searching by account number: {prop.bsa_account_number}")
                    bill_data = await scraper.search_by_account(prop.bsa_account_number)

                # If no result, try searching by address
                if not bill_data:
                    # Extract just the street address for search
                    street_address = prop.address.split(',')[0].strip()
                    logger.info(f"Account search failed, trying address: {street_address}")
                    bill_data = await scraper.search_by_address(street_address)

                if bill_data:
                    # Create new bill record
                    bill = WaterBill(
                        property_id=prop.id,
                        amount_due=bill_data.amount_due,
                        previous_balance=bill_data.previous_balance,
                        current_charges=bill_data.current_charges,
                        late_fees=bill_data.late_fees,
                        payments_received=bill_data.payments_received,
                        statement_date=bill_data.statement_date,
                        due_date=bill_data.due_date,
                        water_usage_gallons=bill_data.water_usage,
                        raw_data=str(bill_data.raw_data) if bill_data.raw_data else None,
                    )
                    bill.status = bill.calculate_status()
                    session.add(bill)

                    # Update property info if available
                    if bill_data.owner_name and not prop.owner_name:
                        prop.owner_name = bill_data.owner_name

                    # Auto-populate parcel number if found
                    if hasattr(bill_data, 'parcel_number') and bill_data.parcel_number and not prop.parcel_number:
                        logger.info(f"Found parcel number for {prop.address}: {bill_data.parcel_number}")
                        prop.parcel_number = bill_data.parcel_number

                    # Auto-populate BSA account number if found via address search
                    if bill_data.account_number and bill_data.account_number != prop.bsa_account_number:
                        logger.info(f"Updating BSA account number: {prop.bsa_account_number} -> {bill_data.account_number}")
                        prop.bsa_account_number = bill_data.account_number

                    await session.commit()
                    logger.info(f"Successfully refreshed bills for {prop.address}")
                else:
                    logger.warning(f"No bill data found for {prop.address}")

    except ImportError:
        logger.error("BSAScraper not available")
    except Exception as e:
        logger.error(f"Error refreshing property {property_id}: {e}")


async def refresh_all_properties():
    """Background task to refresh all active properties"""
    try:
        from scraper.bsa_scraper import BSAScraper

        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.is_active == True)
            )
            properties = result.scalars().all()

            logger.info(f"Starting refresh for {len(properties)} properties")

            async with BSAScraper() as scraper:
                for prop in properties:
                    try:
                        await refresh_single_property(prop.id)
                    except Exception as e:
                        logger.error(f"Error refreshing {prop.address}: {e}")
                        continue

            logger.info("Completed refresh for all properties")

    except ImportError:
        logger.error("BSAScraper not available")
    except Exception as e:
        logger.error(f"Error in bulk refresh: {e}")




@router.get("/property-lookup")
async def api_property_lookup(address: str):
    """
    Look up property details by address using web search.
    Searches for property listings and extracts details.
    """
    if not address or len(address) < 5:
        return {"success": False, "message": "Please provide a valid address"}

    logger.info(f"Looking up property: {address}")

    try:
        # Use web search to find property information
        property_data = await lookup_via_web_search(address)

        if property_data:
            logger.info(f"Found via web search: {property_data}")
            return {
                "success": True,
                **property_data
            }

        # Fallback to direct lookups
        property_data = await lookup_zillow(address)
        if property_data:
            return {"success": True, **property_data}

        property_data = await lookup_redfin(address)
        if property_data:
            return {"success": True, **property_data}

        return {
            "success": False,
            "message": "Could not find property details. Please enter manually."
        }

    except Exception as e:
        logger.error(f"Property lookup error: {e}")
        return {
            "success": False,
            "message": "Property lookup service error. Please enter details manually."
        }


async def lookup_via_web_search(address: str) -> dict:
    """
    Look up property data using web search results.
    Searches for the address and extracts property details from results.
    """
    import json

    try:
        clean_address = address.replace(',', ' ').strip()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        }

        async with aiohttp.ClientSession() as session:
            # Use DuckDuckGo HTML search (more reliable than APIs)
            search_query = f"{clean_address} zillow beds baths"
            search_url = f"https://html.duckduckgo.com/html/?q={search_query}"

            logger.info(f"Web search URL: {search_url}")

            async with session.get(search_url, headers=headers, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"DuckDuckGo search failed: {response.status}")
                    return None

                html = await response.text()
                logger.info(f"Web search got {len(html)} bytes")

                # Strip HTML tags for cleaner matching
                clean_html = re.sub(r'<[^>]+>', ' ', html)
                clean_html = re.sub(r'\s+', ' ', clean_html)

                # Debug: check if bed/bath appear in clean text
                has_bed = ' bed' in clean_html.lower()
                has_bath = ' bath' in clean_html.lower()
                logger.info(f"Web search clean text: has_bed={has_bed}, has_bath={has_bath}")

                property_data = {}

                # Look for property details in search snippets
                # Pattern: "X bed, Y bath, Z sqft" or similar variations

                # Bedrooms - look for patterns like "3 bed", "3 beds", "3 bedroom"
                bed_match = re.search(r'(\d+)\s*(?:bed|beds|bedroom|bedrooms|bd|br)\b', clean_html, re.IGNORECASE)
                if bed_match:
                    beds = int(bed_match.group(1))
                    if 0 <= beds <= 20:
                        property_data["bedrooms"] = beds

                # Bathrooms - look for patterns like "2 bath", "2.5 baths"
                bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|baths|bathroom|bathrooms|ba)\b', clean_html, re.IGNORECASE)
                if bath_match:
                    baths = float(bath_match.group(1))
                    if 0.5 <= baths <= 20:
                        property_data["bathrooms"] = baths

                # Square feet - look for patterns like "1,500 sqft", "1500 sq ft"
                sqft_match = re.search(r'([\d,]+)\s*(?:sqft|sq\s*ft|square\s*feet|sf)\b', clean_html, re.IGNORECASE)
                if sqft_match:
                    sqft = int(sqft_match.group(1).replace(',', ''))
                    if 200 <= sqft <= 50000:
                        property_data["square_feet"] = sqft

                # Year built - look for "built in YYYY" or "year built: YYYY"
                year_match = re.search(r'(?:built\s*(?:in)?\s*|year\s*built\s*:?\s*)(\d{4})\b', clean_html, re.IGNORECASE)
                if year_match:
                    year = int(year_match.group(1))
                    if 1800 <= year <= 2030:
                        property_data["year_built"] = year

                # Property type
                if re.search(r'single\s*family', clean_html, re.IGNORECASE):
                    property_data["property_type"] = "Single Family"
                elif re.search(r'(?:multi\s*family|duplex|triplex)', clean_html, re.IGNORECASE):
                    property_data["property_type"] = "Multi-Family"
                elif re.search(r'condo(?:minium)?', clean_html, re.IGNORECASE):
                    property_data["property_type"] = "Condo"
                elif re.search(r'townhouse|townhome', clean_html, re.IGNORECASE):
                    property_data["property_type"] = "Townhouse"

                # Lot size - look for "X acres" or "X sqft lot"
                lot_match = re.search(r'([\d.]+)\s*(?:acre|acres)\b', clean_html, re.IGNORECASE)
                if lot_match:
                    acres = float(lot_match.group(1))
                    if 0.01 <= acres <= 1000:
                        property_data["lot_size"] = f"{acres:.2f} acres"

                logger.info(f"Web search extracted: beds={bed_match.group(0) if bed_match else None}, baths={bath_match.group(0) if bath_match else None}, sqft={sqft_match.group(0) if sqft_match else None}")

                if property_data:
                    logger.info(f"Web search found: {property_data}")
                    return property_data
                else:
                    logger.info("Web search: No valid property data extracted")

        return None

    except Exception as e:
        logger.error(f"Web search lookup error: {e}", exc_info=True)
        return None


async def lookup_county_assessor(address: str) -> dict:
    """
    Look up property data from Michigan county assessor records.
    Tries multiple sources including Detroit Open Data.
    """
    import json

    try:
        # Extract just the street address (remove city, state, zip)
        street_address = address.split(',')[0].strip().upper()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            # Try Detroit Open Data Portal (Socrata API - free and reliable)
            # This has parcel data for Detroit properties
            detroit_url = "https://data.detroitmi.gov/resource/qhfc-4cw8.json"
            params = {
                "$where": f"upper(address) like '%{street_address}%'",
                "$limit": 1
            }

            try:
                async with session.get(detroit_url, params=params, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            parcel = data[0]
                            property_data = {}

                            # Extract available fields
                            if parcel.get("year_built"):
                                try:
                                    year = int(float(parcel["year_built"]))
                                    if 1800 <= year <= 2030:
                                        property_data["year_built"] = year
                                except:
                                    pass

                            if parcel.get("total_floor_area"):
                                try:
                                    sqft = int(float(parcel["total_floor_area"]))
                                    if 200 <= sqft <= 50000:
                                        property_data["square_feet"] = sqft
                                except:
                                    pass

                            if parcel.get("total_acreage"):
                                try:
                                    acres = float(parcel["total_acreage"])
                                    if acres > 0:
                                        property_data["lot_size"] = f"{acres:.2f} acres"
                                except:
                                    pass

                            # Property class often indicates type
                            prop_class = parcel.get("property_class", "").lower()
                            if "residential" in prop_class or "single" in prop_class:
                                property_data["property_type"] = "Single Family"
                            elif "multi" in prop_class or "apartment" in prop_class:
                                property_data["property_type"] = "Multi-Family"
                            elif "condo" in prop_class:
                                property_data["property_type"] = "Condo"

                            if property_data:
                                logger.info(f"Found via Detroit Open Data: {property_data}")
                                return property_data
            except Exception as e:
                logger.debug(f"Detroit Open Data lookup failed: {e}")

            # Try Wayne County Open Data
            wayne_url = "https://openwaynedata.wayne.gov/resource/xwnu-3y9n.json"
            params = {
                "$where": f"upper(propstreetcombined) like '%{street_address}%'",
                "$limit": 1
            }

            try:
                async with session.get(wayne_url, params=params, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            parcel = data[0]
                            property_data = {}

                            if parcel.get("resb_yearbuilt"):
                                try:
                                    year = int(parcel["resb_yearbuilt"])
                                    if 1800 <= year <= 2030:
                                        property_data["year_built"] = year
                                except:
                                    pass

                            if parcel.get("resb_groundfloorarea"):
                                try:
                                    sqft = int(float(parcel["resb_groundfloorarea"]))
                                    if 200 <= sqft <= 50000:
                                        property_data["square_feet"] = sqft
                                except:
                                    pass

                            if parcel.get("resb_fullbaths"):
                                try:
                                    baths = float(parcel["resb_fullbaths"])
                                    half = float(parcel.get("resb_halfbaths", 0) or 0)
                                    total = baths + (half * 0.5)
                                    if 0.5 <= total <= 20:
                                        property_data["bathrooms"] = total
                                except:
                                    pass

                            if parcel.get("resb_bedrooms"):
                                try:
                                    beds = int(parcel["resb_bedrooms"])
                                    if 0 <= beds <= 20:
                                        property_data["bedrooms"] = beds
                                except:
                                    pass

                            if property_data:
                                logger.info(f"Found via Wayne County: {property_data}")
                                return property_data
            except Exception as e:
                logger.debug(f"Wayne County lookup failed: {e}")

        return None

    except Exception as e:
        logger.error(f"County assessor lookup error: {e}")
        return None


async def lookup_zillow(address: str) -> dict:
    """Attempt to get property data from Zillow using their search API"""
    import json

    try:
        # Clean up address for search
        clean_address = address.split(',')[0].strip()  # Just street address

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with aiohttp.ClientSession() as session:
            # Try Zillow's public search API
            search_url = "https://www.zillow.com/search/GetSearchPageState.htm"
            params = {
                "searchQueryState": json.dumps({
                    "usersSearchTerm": clean_address,
                    "isMapVisible": False,
                    "filterState": {},
                    "isListVisible": True
                }),
                "wants": json.dumps({"cat1": ["listResults"]}),
                "requestId": 1
            }

            async with session.get(search_url, params=params, headers=headers, timeout=15) as response:
                logger.debug(f"Zillow API response status: {response.status}")
                if response.status == 200:
                    try:
                        data = await response.json()
                        results = data.get("cat1", {}).get("searchResults", {}).get("listResults", [])
                        if results:
                            prop = results[0]
                            property_data = {}
                            if prop.get("beds"):
                                property_data["bedrooms"] = int(prop["beds"])
                            if prop.get("baths"):
                                property_data["bathrooms"] = float(prop["baths"])
                            if prop.get("area"):
                                property_data["square_feet"] = int(prop["area"])
                            if property_data:
                                logger.info(f"Found via Zillow API: {property_data}")
                                return property_data
                    except Exception as e:
                        logger.debug(f"Zillow API parse error: {e}")

            # Fallback: Try scraping the property page directly
            formatted_address = clean_address.replace(' ', '-').replace(',', '').replace('.', '')
            page_url = f"https://www.zillow.com/homes/{formatted_address}_rb/"

            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

            async with session.get(page_url, headers=headers, timeout=15, allow_redirects=True) as response:
                logger.debug(f"Zillow page response status: {response.status}")
                if response.status != 200:
                    return None

                html = await response.text()
                data = {}

                # Try to find bedrooms
                bed_match = re.search(r'"bedrooms?"\s*:\s*(\d+)', html)
                if bed_match:
                    data["bedrooms"] = int(bed_match.group(1))

                # Try to find bathrooms
                bath_match = re.search(r'"bathrooms?"\s*:\s*([\d.]+)', html)
                if bath_match:
                    data["bathrooms"] = float(bath_match.group(1))

                # Try to find square feet
                sqft_match = re.search(r'"livingArea"\s*:\s*(\d+)', html)
                if sqft_match:
                    data["square_feet"] = int(sqft_match.group(1))

                # Try to find year built
                year_match = re.search(r'"yearBuilt"\s*:\s*(\d{4})', html)
                if year_match:
                    data["year_built"] = int(year_match.group(1))

                # Try to find property type
                type_match = re.search(r'"homeType"\s*:\s*"([^"]+)"', html)
                if type_match:
                    home_type = type_match.group(1).upper()
                    if "SINGLE" in home_type:
                        data["property_type"] = "Single Family"
                    elif "MULTI" in home_type:
                        data["property_type"] = "Multi-Family"
                    elif "CONDO" in home_type:
                        data["property_type"] = "Condo"

                if data:
                    logger.info(f"Found via Zillow scrape: {data}")
                    return data

        return None

    except Exception as e:
        logger.error(f"Zillow lookup error: {e}")
        return None


@router.get("/search")
async def api_search(request: Request, q: str = ""):
    """Global search across properties, tenants, and work orders"""
    from webapp.auth.dependencies import get_current_user

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not q or len(q) < 2:
        return {"properties": [], "tenants": [], "work_orders": []}

    term = f"%{q}%"

    async with get_session() as session:
        # Search properties by address
        prop_result = await session.execute(
            select(Property)
            .where(Property.is_active == True, Property.address.ilike(term))
            .limit(5)
        )
        properties = [
            {"id": p.id, "address": p.address, "city": p.city or ""}
            for p in prop_result.scalars().all()
        ]

        # Search tenants by name
        tenant_result = await session.execute(
            select(Tenant)
            .where(Tenant.is_active == True, Tenant.name.ilike(term))
            .options(selectinload(Tenant.property_ref))
            .limit(5)
        )
        tenants = [
            {
                "id": t.id,
                "name": t.name,
                "property": t.property_ref.address if t.property_ref else "",
            }
            for t in tenant_result.scalars().all()
        ]

        # Search work orders by title
        wo_result = await session.execute(
            select(WorkOrder)
            .where(WorkOrder.title.ilike(term))
            .options(selectinload(WorkOrder.property_ref))
            .order_by(WorkOrder.created_at.desc())
            .limit(5)
        )
        work_orders = [
            {
                "id": w.id,
                "title": w.title,
                "status": w.status.value if w.status else "",
                "property": w.property_ref.address if w.property_ref else "",
            }
            for w in wo_result.scalars().all()
        ]

    return {"properties": properties, "tenants": tenants, "work_orders": work_orders}


@router.get("/unread-count")
async def api_unread_count(request: Request):
    """Get count of unread inbound SMS messages"""
    from webapp.auth.dependencies import get_current_user
    from sqlalchemy import func

    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    async with get_session() as session:
        result = await session.execute(
            select(func.count(SMSMessage.id))
            .where(
                SMSMessage.direction == MessageDirection.INBOUND,
                SMSMessage.status == "received",
            )
        )
        count = result.scalar() or 0

    return {"unread": count}


async def lookup_redfin(address: str) -> dict:
    """Attempt to get property data from Redfin"""
    import json

    try:
        clean_address = address.split(',')[0].strip()

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            # Step 1: Search for the property
            search_url = f"https://www.redfin.com/stingray/do/location-autocomplete?location={clean_address}&v=2"

            async with session.get(search_url, headers=headers, timeout=10) as response:
                if response.status != 200:
                    return None

                text = await response.text()

                # Redfin returns {}&&{json} format
                if "&&" in text:
                    text = text.split("&&")[1]

                try:
                    data = json.loads(text)
                except:
                    return None

                # Get the property URL
                property_url = None
                if "payload" in data:
                    sections = data["payload"].get("sections", [])
                    for section in sections:
                        rows = section.get("rows", [])
                        for row in rows:
                            if row.get("url") and row.get("type") == "2":  # Type 2 is usually address
                                property_url = row["url"]
                                break
                        if property_url:
                            break

                    # Also check exactMatch
                    if not property_url and data["payload"].get("exactMatch"):
                        property_url = data["payload"]["exactMatch"].get("url")

                if not property_url:
                    return None

                # Step 2: Fetch the property page
                full_url = f"https://www.redfin.com{property_url}"
                headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

                async with session.get(full_url, headers=headers, timeout=15) as response:
                    if response.status != 200:
                        return None

                    html = await response.text()
                    property_data = {}

                    # Look for property data in the page
                    # Redfin embeds data in a script tag

                    # Bedrooms
                    bed_match = re.search(r'"beds"\s*:\s*(\d+)', html)
                    if bed_match:
                        property_data["bedrooms"] = int(bed_match.group(1))

                    # Bathrooms
                    bath_match = re.search(r'"baths"\s*:\s*([\d.]+)', html)
                    if bath_match:
                        property_data["bathrooms"] = float(bath_match.group(1))

                    # Square feet
                    sqft_match = re.search(r'"sqFt"\s*:\s*\{\s*"value"\s*:\s*(\d+)', html)
                    if not sqft_match:
                        sqft_match = re.search(r'"sqftDisplay"\s*:\s*"([\d,]+)', html)
                    if sqft_match:
                        property_data["square_feet"] = int(sqft_match.group(1).replace(',', ''))

                    # Year built
                    year_match = re.search(r'"yearBuilt"\s*:\s*\{\s*"value"\s*:\s*(\d{4})', html)
                    if not year_match:
                        year_match = re.search(r'Built in (\d{4})', html)
                    if year_match:
                        property_data["year_built"] = int(year_match.group(1))

                    # Property type
                    type_match = re.search(r'"propertyType"\s*:\s*"([^"]+)"', html)
                    if type_match:
                        ptype = type_match.group(1).lower()
                        if "single" in ptype:
                            property_data["property_type"] = "Single Family"
                        elif "multi" in ptype or "duplex" in ptype:
                            property_data["property_type"] = "Multi-Family"
                        elif "condo" in ptype:
                            property_data["property_type"] = "Condo"
                        elif "town" in ptype:
                            property_data["property_type"] = "Townhouse"

                    if property_data:
                        logger.info(f"Found via Redfin: {property_data}")
                        return property_data

        return None

    except Exception as e:
        logger.error(f"Redfin lookup error: {e}")
        return None
