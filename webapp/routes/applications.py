"""Tenant application and screening routes"""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, TenantApplication, ApplicationStatus
from webapp.auth.dependencies import get_current_user
from webapp.config import web_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["applications"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# =============================================================================
# Public Routes (no auth)
# =============================================================================

@router.get("/apply/{property_id}", response_class=HTMLResponse)
async def apply_form(request: Request, property_id: int):
    """Render the rental application form for a property."""
    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .where(Property.id == property_id, Property.is_active == True)
            .options(selectinload(Property.photos), selectinload(Property.tenants))
        )
        prop = result.scalar_one_or_none()

        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        active_tenants = [t for t in prop.tenants if t.is_active]
        is_available = len(active_tenants) == 0

        # Get rent
        rent = None
        if prop.monthly_rent:
            rent = float(prop.monthly_rent)

        # Primary photo
        primary_photo = None
        if prop.featured_photo_url:
            primary_photo = prop.featured_photo_url
        elif prop.photos:
            primary = next((p for p in prop.photos if p.is_primary), None)
            primary_photo = primary.url if primary else prop.photos[0].url if prop.photos else None

    return templates.TemplateResponse("public/apply.html", {
        "request": request,
        "property": prop,
        "rent": rent,
        "photo": primary_photo,
        "is_available": is_available,
        "screening_fee": web_config.tenantreportx_applicant_fee,
    })


def _parse_money(val: str):
    """Parse a dollar string like '$1,200' to float."""
    val = val.strip().replace(",", "").replace("$", "")
    try:
        return float(val) if val else None
    except ValueError:
        return None


def _collect_dynamic_entries(form, prefix_fields: dict, max_count=20):
    """Collect dynamically-added form entries (occupants, past addresses, etc).

    prefix_fields maps a suffix like 'name' to 'occupant_name_'.
    Returns a list of dicts for entries where at least one field is filled.
    """
    entries = []
    for i in range(1, max_count + 1):
        entry = {}
        any_filled = False
        for key, form_prefix in prefix_fields.items():
            val = form.get(f"{form_prefix}{i}", "").strip()
            if val:
                any_filled = True
            entry[key] = val
        if any_filled:
            entries.append(entry)
    return entries


@router.post("/apply/{property_id}")
async def apply_submit(request: Request, property_id: int):
    """Process a rental application submission."""
    async with get_session() as session:
        # Verify property exists and is active
        result = await session.execute(
            select(Property).where(Property.id == property_id, Property.is_active == True)
        )
        prop = result.scalar_one_or_none()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found")

        form = await request.form()

        # --- Core column fields ---
        income = _parse_money(form.get("income", ""))

        voucher_amount = None
        has_voucher = form.get("has_section8_voucher") == "on"
        if has_voucher:
            voucher_amount = _parse_money(form.get("voucher_amount", ""))

        move_in_date = None
        mid_str = form.get("move_in_date", "").strip()
        if mid_str:
            try:
                move_in_date = datetime.strptime(mid_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        applicant_dob = None
        dob_str = form.get("dob", "").strip()
        if dob_str:
            try:
                applicant_dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        # Build full current address from step 3
        addr_parts = [
            form.get("current_address", "").strip(),
            form.get("current_city", "").strip(),
            form.get("current_state", "").strip(),
            form.get("current_zip", "").strip(),
        ]
        full_current_address = ", ".join(p for p in addr_parts if p)

        # Count occupants from dynamic entries
        occupants = _collect_dynamic_entries(form, {
            "name": "occupant_name_",
            "relationship": "occupant_relationship_",
            "age": "occupant_age_",
        })
        num_occupants = len(occupants) + 1  # +1 for the applicant

        # --- Extended application data (JSON blob) ---
        app_data = {}

        # Step 2: Occupants & Co-signers
        app_data["occupants"] = occupants
        cosigners = _collect_dynamic_entries(form, {
            "name": "cosigner_name_",
            "phone": "cosigner_phone_",
        })
        app_data["cosigners"] = cosigners

        # Step 3: Residential history
        app_data["current_address"] = {
            "address": form.get("current_address", "").strip(),
            "city": form.get("current_city", "").strip(),
            "state": form.get("current_state", "").strip(),
            "zip": form.get("current_zip", "").strip(),
            "since": form.get("current_addr_since", "").strip(),
            "rent": form.get("current_rent", "").strip(),
            "landlord_name": form.get("current_landlord_name", "").strip(),
            "landlord_phone": form.get("current_landlord_phone", "").strip(),
            "reason_leaving": form.get("current_reason_leaving", "").strip(),
        }
        past_addresses = _collect_dynamic_entries(form, {
            "address": "past_address_",
            "city": "past_city_",
            "state": "past_state_",
            "zip": "past_zip_",
            "from": "past_addr_from_",
            "to": "past_addr_to_",
            "landlord_name": "past_landlord_name_",
            "landlord_phone": "past_landlord_phone_",
            "reason_leaving": "past_reason_leaving_",
        })
        app_data["past_addresses"] = past_addresses

        # Step 4: Employment
        app_data["employment"] = {
            "is_unemployed": form.get("is_unemployed") == "on",
            "employer": form.get("employer", "").strip(),
            "position": form.get("position", "").strip(),
            "start_date": form.get("employer_start_date", "").strip(),
            "supervisor_name": form.get("supervisor_name", "").strip(),
            "supervisor_phone": form.get("supervisor_phone", "").strip(),
        }
        past_employers = _collect_dynamic_entries(form, {
            "name": "past_employer_name_",
            "position": "past_employer_position_",
            "from": "past_employer_from_",
            "to": "past_employer_to_",
        })
        app_data["past_employers"] = past_employers

        # Step 5: Other income
        app_data["other_income"] = {
            "has_other_income": form.get("has_other_income") == "yes",
            "source": form.get("other_income_source", "").strip(),
            "amount": form.get("other_income_amount", "").strip(),
        }

        # Step 6: General information
        app_data["animals"] = {
            "has_animals": form.get("has_animals") == "yes",
            "type": form.get("animal_type", "").strip(),
            "weight": form.get("animal_weight", "").strip(),
        }
        app_data["vehicle"] = {
            "has_vehicle": form.get("has_vehicle") == "yes",
            "info": form.get("vehicle_info", "").strip(),
            "plate": form.get("vehicle_plate", "").strip(),
        }
        app_data["smoker"] = form.get("smoker", "no")
        app_data["special_requests"] = form.get("special_requests", "").strip()

        # Step 7: Background
        app_data["background"] = {
            "prior_eviction": form.get("prior_eviction") == "yes",
            "prior_criminal": form.get("prior_criminal") == "yes",
            "prior_bankruptcy": form.get("prior_bankruptcy") == "yes",
        }

        # Step 8: Emergency contact & referral
        app_data["emergency_contact"] = {
            "name": form.get("emergency_contact_name", "").strip(),
            "relationship": form.get("emergency_contact_relationship", "").strip(),
            "phone": form.get("emergency_contact_phone", "").strip(),
        }
        app_data["referral_source"] = form.get("referral_source", "").strip()

        application = TenantApplication(
            property_id=property_id,
            applicant_first_name=form.get("first_name", "").strip(),
            applicant_last_name=form.get("last_name", "").strip(),
            applicant_email=form.get("email", "").strip(),
            applicant_phone=form.get("phone", "").strip(),
            applicant_dob=applicant_dob,
            applicant_type=form.get("applicant_type", "tenant").strip(),
            applicant_current_address=full_current_address,
            applicant_employer=form.get("employer", "").strip(),
            applicant_income=income,
            applicant_move_in_date=move_in_date,
            applicant_num_occupants=num_occupants,
            has_section8_voucher=has_voucher,
            voucher_amount=voucher_amount,
            applicant_notes=form.get("notes", "").strip(),
            application_data=json.dumps(app_data),
            status=ApplicationStatus.PENDING,
        )
        session.add(application)
        await session.flush()
        app_id = application.id

        # Submit screening if configured
        if web_config.has_tenantreportx:
            try:
                from webapp.services.screening_service import submit_screening
                await submit_screening(app_id)
            except Exception as e:
                logger.error(f"Screening submission failed: {e}")

        # Send Telegram notification
        try:
            from webapp.services.telegram_service import telegram_service
            name = f"{application.applicant_first_name} {application.applicant_last_name}"
            app_type = application.applicant_type or "tenant"
            msg = (
                f"\U0001f4dd *New Rental Application*\n\n"
                f"*{name}*"
            )
            if app_type == "cosigner":
                msg += " _(co-signer)_"
            msg += (
                f"\n  \U0001f3e0 {prop.address}\n"
                f"  \U0001f4e7 {application.applicant_email}\n"
            )
            if application.applicant_phone:
                msg += f"  \U0001f4f1 {application.applicant_phone}\n"
            if has_voucher:
                msg += f"  \U0001f3db Section 8 Voucher"
                if voucher_amount:
                    msg += f": ${voucher_amount:,.0f}"
                msg += "\n"
            if app_data.get("background", {}).get("prior_eviction"):
                msg += "  \u26a0\ufe0f Prior eviction disclosed\n"
            if app_data.get("background", {}).get("prior_criminal"):
                msg += "  \u26a0\ufe0f Prior criminal record disclosed\n"
            await telegram_service.send_message(msg)
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")

    return RedirectResponse(url=f"/apply/{property_id}/confirmation", status_code=303)


@router.get("/apply/{property_id}/confirmation", response_class=HTMLResponse)
async def apply_confirmation(request: Request, property_id: int):
    """Thank-you page after application submission."""
    async with get_session() as session:
        result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = result.scalar_one_or_none()

    return templates.TemplateResponse("public/apply_confirmation.html", {
        "request": request,
        "property": prop,
    })


# =============================================================================
# Webhook
# =============================================================================

@router.post("/api/screening/webhook")
async def screening_webhook(request: Request):
    """Handle TenantReportX webhook callbacks."""
    # Verify webhook secret
    if web_config.tenantreportx_webhook_secret:
        signature = request.headers.get("X-Webhook-Signature", "")
        body = await request.body()
        expected = hmac.new(
            web_config.tenantreportx_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return JSONResponse({"error": "Invalid signature"}, status_code=401)

    payload = await request.json()

    try:
        from webapp.services.screening_service import process_webhook
        result = await process_webhook(payload)
        return JSONResponse(result)
    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        return JSONResponse({"error": "Processing failed"}, status_code=500)


# =============================================================================
# Admin Routes (require auth)
# =============================================================================

@router.get("/applications", response_class=HTMLResponse)
async def applications_list(request: Request, status: str = None):
    """List all tenant applications with optional status filter."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        query = (
            select(TenantApplication)
            .options(selectinload(TenantApplication.property_ref))
            .order_by(desc(TenantApplication.applied_at))
        )

        if status and status != "all":
            try:
                status_enum = ApplicationStatus(status)
                query = query.where(TenantApplication.status == status_enum)
            except ValueError:
                pass

        result = await session.execute(query)
        applications = result.scalars().all()

        # Get counts per status
        count_result = await session.execute(select(TenantApplication))
        all_apps = count_result.scalars().all()
        counts = {
            "all": len(all_apps),
            "pending": sum(1 for a in all_apps if a.status == ApplicationStatus.PENDING),
            "screening": sum(1 for a in all_apps if a.status == ApplicationStatus.SCREENING),
            "completed": sum(1 for a in all_apps if a.status == ApplicationStatus.COMPLETED),
            "approved": sum(1 for a in all_apps if a.status == ApplicationStatus.APPROVED),
            "denied": sum(1 for a in all_apps if a.status == ApplicationStatus.DENIED),
        }

    return templates.TemplateResponse("applications/list.html", {
        "request": request,
        "user": user,
        "applications": applications,
        "current_status": status or "all",
        "counts": counts,
    })


@router.get("/applications/{application_id}", response_class=HTMLResponse)
async def application_detail(request: Request, application_id: int):
    """View application detail with screening results."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(TenantApplication)
            .where(TenantApplication.id == application_id)
            .options(selectinload(TenantApplication.property_ref))
        )
        application = result.scalar_one_or_none()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")

        # Parse extended application data
        app_data = {}
        if application.application_data:
            try:
                app_data = json.loads(application.application_data)
            except (json.JSONDecodeError, TypeError):
                pass

    return templates.TemplateResponse("applications/detail.html", {
        "request": request,
        "user": user,
        "application": application,
        "app_data": app_data,
    })


@router.post("/applications/{application_id}/decide")
async def application_decide(request: Request, application_id: int):
    """Approve or deny an application."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    decision = form.get("decision", "")
    notes = form.get("landlord_notes", "").strip()

    if decision not in ("approved", "denied"):
        return RedirectResponse(url=f"/applications/{application_id}", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(TenantApplication).where(TenantApplication.id == application_id)
        )
        application = result.scalar_one_or_none()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")

        application.status = ApplicationStatus(decision)
        application.landlord_notes = notes
        application.decided_at = datetime.utcnow()

    return RedirectResponse(url=f"/applications/{application_id}", status_code=303)
