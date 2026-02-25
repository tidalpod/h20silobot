"""Lease Builder wizard routes — step-by-step Michigan lease creation"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    LeaseBuilder, LeaseBuilderStatus, LeaseDocument, LeaseStatus,
    Property, Tenant, EntityConfig,
)
from webapp.auth.dependencies import get_current_user
from webapp.services.lease_pdf_service import generate_lease_pdf

router = APIRouter(tags=["lease-builder"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TOTAL_STEPS = 6


def _get_lease_data(builder: LeaseBuilder) -> dict:
    """Parse lease_data JSON or return empty dict."""
    if builder.lease_data:
        try:
            return json.loads(builder.lease_data)
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _save_lease_data(builder: LeaseBuilder, data: dict):
    """Serialize lease_data JSON."""
    builder.lease_data = json.dumps(data)
    builder.updated_at = datetime.utcnow()


# =============================================================================
# List / Start
# =============================================================================

@router.get("/", response_class=HTMLResponse)
async def builder_list(request: Request):
    """List all lease builder drafts."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseBuilder)
            .options(
                selectinload(LeaseBuilder.property_ref),
                selectinload(LeaseBuilder.tenant_ref),
            )
            .order_by(desc(LeaseBuilder.updated_at))
        )
        builders = result.scalars().all()

    return templates.TemplateResponse(
        "leases/builder_list.html",
        {"request": request, "user": user, "builders": builders, "total_steps": TOTAL_STEPS},
    )


@router.get("/new", response_class=HTMLResponse)
async def builder_start(request: Request):
    """Start: select property + tenant."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        tenants_result = await session.execute(
            select(Tenant).where(Tenant.is_active == True).order_by(Tenant.name)
        )
        tenants = tenants_result.scalars().all()

    return templates.TemplateResponse(
        "leases/builder_start.html",
        {"request": request, "user": user, "properties": properties, "tenants": tenants},
    )


@router.post("/new")
async def builder_create(request: Request):
    """Create LeaseBuilder record and redirect to step 1."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    property_id = int(form.get("property_id", 0))
    tenant_id = int(form.get("tenant_id", 0)) if form.get("tenant_id") else None

    if not property_id:
        return RedirectResponse(url="/leases/builder/new?error=no_property", status_code=303)

    async with get_session() as session:
        # Get property for auto-fill
        prop_result = await session.execute(
            select(Property).where(Property.id == property_id)
        )
        prop = prop_result.scalar_one_or_none()

        # Get tenant for auto-fill
        tenant_data = {}
        if tenant_id:
            tenant_result = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = tenant_result.scalar_one_or_none()
            if tenant:
                tenant_data = {
                    "name": tenant.name,
                    "email": tenant.email or "",
                    "phone": tenant.phone or "",
                }

        # Get entity config for auto-fill
        landlord = {}
        if prop and prop.entity:
            entity_result = await session.execute(
                select(EntityConfig).where(EntityConfig.entity_name == prop.entity)
            )
            entity = entity_result.scalar_one_or_none()
            if entity:
                landlord = {
                    "type": "company",
                    "entity_name": entity.entity_name,
                    "owner_name": entity.owner_name or "",
                    "email": entity.email or "",
                    "phone": entity.phone or "",
                    "mailing_address": entity.mailing_address or "",
                }

        # Initial lease data with auto-fill
        initial_data = {
            "tenants": [tenant_data] if tenant_data else [],
            "landlord": landlord,
            "monthly_rent": float(prop.monthly_rent) if prop and prop.monthly_rent else 0,
            "rent_due_day": 1,
            "late_fee_daily": 15,
            "late_fee_grace_days": 5,
            "late_fee_max_days": 5,
            "payment_methods": ["ach", "bluedeer"],
            "smoking_policy": "not_permitted",
            "renters_insurance_required": True,
            "maintenance_communication": ["bluedeer_portal", "email", "text"],
            "lead_paint_disclosure": bool(prop and prop.year_built and prop.year_built < 1978),
        }

        builder = LeaseBuilder(
            property_id=property_id,
            tenant_id=tenant_id,
            current_step=1,
            status=LeaseBuilderStatus.DRAFT,
            lease_data=json.dumps(initial_data),
        )
        session.add(builder)
        await session.flush()
        builder_id = builder.id

    return RedirectResponse(url=f"/leases/builder/{builder_id}/step/1", status_code=303)


# =============================================================================
# Wizard Steps
# =============================================================================

@router.get("/{builder_id}/step/{step}", response_class=HTMLResponse)
async def builder_step(request: Request, builder_id: int, step: int):
    """Render wizard step N."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if step < 1 or step > TOTAL_STEPS:
        return RedirectResponse(url=f"/leases/builder/{builder_id}/step/1", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseBuilder)
            .where(LeaseBuilder.id == builder_id)
            .options(
                selectinload(LeaseBuilder.property_ref),
                selectinload(LeaseBuilder.tenant_ref),
            )
        )
        builder = result.scalar_one_or_none()
        if not builder:
            return RedirectResponse(url="/leases/builder", status_code=303)

        data = _get_lease_data(builder)

        # Load entity configs for step 3
        entities = []
        if step == 3:
            ent_result = await session.execute(
                select(EntityConfig).order_by(EntityConfig.entity_name)
            )
            entities = ent_result.scalars().all()

    return templates.TemplateResponse(
        f"leases/builder_step{step}.html",
        {
            "request": request,
            "user": user,
            "builder": builder,
            "data": data,
            "step": step,
            "total_steps": TOTAL_STEPS,
            "entities": entities,
            "property": builder.property_ref,
        },
    )


@router.post("/{builder_id}/step/{step}")
async def save_step(request: Request, builder_id: int, step: int):
    """Save step N data. Redirect to next step or stay (save-only)."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    action = form.get("action", "continue")  # "save" or "continue"

    async with get_session() as session:
        result = await session.execute(
            select(LeaseBuilder).where(LeaseBuilder.id == builder_id)
        )
        builder = result.scalar_one_or_none()
        if not builder:
            return RedirectResponse(url="/leases/builder", status_code=303)

        data = _get_lease_data(builder)

        # Merge form data based on step
        if step == 1:
            data["lease_type"] = form.get("lease_type", "fixed")
            data["start_date"] = form.get("start_date", "")
            data["end_date"] = form.get("end_date", "")
            data["expiration_action"] = form.get("expiration_action", "continue_mtm")

        elif step == 2:
            data["monthly_rent"] = float(form.get("monthly_rent", 0) or 0)
            data["rent_due_day"] = int(form.get("rent_due_day", 1) or 1)
            data["late_fee_daily"] = float(form.get("late_fee_daily", 15) or 15)
            data["late_fee_grace_days"] = int(form.get("late_fee_grace_days", 5) or 5)
            data["late_fee_max_days"] = int(form.get("late_fee_max_days", 5) or 5)
            data["pet_rent"] = float(form.get("pet_rent", 0) or 0)
            data["prorated_rent"] = float(form.get("prorated_rent") or 0) if form.get("prorated_rent") else None
            data["security_deposit"] = float(form.get("security_deposit", 0) or 0)
            data["pet_deposit"] = float(form.get("pet_deposit", 0) or 0)
            data["other_deposit"] = float(form.get("other_deposit", 0) or 0)
            data["deposit_bank_name"] = form.get("deposit_bank_name", "")
            data["deposit_bank_address"] = form.get("deposit_bank_address", "")
            data["payment_methods"] = form.getlist("payment_methods")

            # Move-in fees (dynamic rows)
            fees = []
            fee_descs = form.getlist("fee_description")
            fee_amts = form.getlist("fee_amount")
            for desc, amt in zip(fee_descs, fee_amts):
                if desc and amt:
                    fees.append({"description": desc, "amount": float(amt)})
            data["move_in_fees"] = fees

        elif step == 3:
            # Tenants
            tenant_names = form.getlist("tenant_name")
            tenant_emails = form.getlist("tenant_email")
            tenant_phones = form.getlist("tenant_phone")
            tenants = []
            for name, email, phone in zip(tenant_names, tenant_emails, tenant_phones):
                if name:
                    tenants.append({"name": name, "email": email, "phone": phone})
            data["tenants"] = tenants

            # Additional occupants
            occ_names = form.getlist("occupant_name")
            occ_ages = form.getlist("occupant_age")
            occ_rels = form.getlist("occupant_relationship")
            occupants = []
            for name, age, rel in zip(occ_names, occ_ages, occ_rels):
                if name:
                    occupants.append({"name": name, "age": int(age or 0), "relationship": rel})
            data["additional_occupants"] = occupants

            # Landlord
            data["landlord"] = {
                "type": form.get("landlord_type", "company"),
                "entity_name": form.get("landlord_entity_name", ""),
                "owner_name": form.get("landlord_owner_name", ""),
                "email": form.get("landlord_email", ""),
                "phone": form.get("landlord_phone", ""),
                "mailing_address": form.get("landlord_mailing_address", ""),
            }

            # Cosigners
            cos_names = form.getlist("cosigner_name")
            cos_emails = form.getlist("cosigner_email")
            cosigners = []
            for name, email in zip(cos_names, cos_emails):
                if name:
                    cosigners.append({"name": name, "email": email})
            data["cosigners"] = cosigners

        elif step == 4:
            data["pets_allowed"] = form.get("pets_allowed") == "true"
            pets = []
            pet_types = form.getlist("pet_type")
            pet_breeds = form.getlist("pet_breed")
            pet_weights = form.getlist("pet_weight")
            pet_ages = form.getlist("pet_age")
            for ptype, breed, weight, age in zip(pet_types, pet_breeds, pet_weights, pet_ages):
                if ptype:
                    pets.append({"type": ptype, "breed": breed, "weight": weight, "age": age})
            data["pets"] = pets
            data["smoking_policy"] = form.get("smoking_policy", "not_permitted")
            data["parking_rules"] = form.get("parking_rules", "")
            data["renters_insurance_required"] = form.get("renters_insurance_required") == "true"

        elif step == 5:
            # Utilities
            utility_names = ["electricity", "gas", "water", "sewer", "trash", "internet", "cable"]
            utilities = {}
            for name in utility_names:
                utilities[name] = form.get(f"utility_{name}", "tenant")
            data["utilities"] = utilities
            data["maintenance_communication"] = form.getlist("maintenance_communication")

            # Keys
            key_types = form.getlist("key_type")
            key_counts = form.getlist("key_count")
            keys = []
            for ktype, count in zip(key_types, key_counts):
                if ktype:
                    keys.append({"type": ktype, "count": int(count or 1)})
            data["keys"] = keys

        elif step == 6:
            data["early_termination"] = form.get("early_termination") == "true"
            data["additional_terms"] = form.get("additional_terms", "")
            data["lead_paint_disclosure"] = form.get("lead_paint_disclosure") == "true"

        _save_lease_data(builder, data)
        builder.current_step = max(builder.current_step, step)

    if action == "continue" and step < TOTAL_STEPS:
        return RedirectResponse(url=f"/leases/builder/{builder_id}/step/{step + 1}", status_code=303)
    elif action == "continue" and step == TOTAL_STEPS:
        return RedirectResponse(url=f"/leases/builder/{builder_id}/review", status_code=303)
    else:
        return RedirectResponse(url=f"/leases/builder/{builder_id}/step/{step}", status_code=303)


# =============================================================================
# Review & Generate
# =============================================================================

@router.get("/{builder_id}/review", response_class=HTMLResponse)
async def builder_review(request: Request, builder_id: int):
    """Review all data before generating."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseBuilder)
            .where(LeaseBuilder.id == builder_id)
            .options(
                selectinload(LeaseBuilder.property_ref),
                selectinload(LeaseBuilder.tenant_ref),
            )
        )
        builder = result.scalar_one_or_none()
        if not builder:
            return RedirectResponse(url="/leases/builder", status_code=303)

        data = _get_lease_data(builder)

    return templates.TemplateResponse(
        "leases/builder_review.html",
        {
            "request": request,
            "user": user,
            "builder": builder,
            "data": data,
            "total_steps": TOTAL_STEPS,
            "property": builder.property_ref,
        },
    )


@router.post("/{builder_id}/generate")
async def builder_generate(request: Request, builder_id: int):
    """Generate PDF and create LeaseDocument."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseBuilder)
            .where(LeaseBuilder.id == builder_id)
            .options(
                selectinload(LeaseBuilder.property_ref),
                selectinload(LeaseBuilder.tenant_ref),
            )
        )
        builder = result.scalar_one_or_none()
        if not builder:
            return RedirectResponse(url="/leases/builder", status_code=303)

        data = _get_lease_data(builder)
        prop = builder.property_ref

        property_info = {
            "address": prop.address if prop else "",
            "city": prop.city if prop else "",
            "state": prop.state or "MI",
            "zip_code": prop.zip_code if prop else "",
            "year_built": prop.year_built if prop else None,
        }
        tenant_info = {
            "name": builder.tenant_ref.name if builder.tenant_ref else "",
            "email": builder.tenant_ref.email if builder.tenant_ref else "",
            "phone": builder.tenant_ref.phone if builder.tenant_ref else "",
        }
        landlord_info = data.get("landlord", {})

        pdf_result = generate_lease_pdf(data, property_info, tenant_info, landlord_info)
        if "error" in pdf_result:
            return RedirectResponse(
                url=f"/leases/builder/{builder_id}/review?error={pdf_result['error']}",
                status_code=303,
            )

        # Create LeaseDocument
        from datetime import date as date_type
        lease_start = None
        lease_end = None
        if data.get("start_date"):
            try:
                lease_start = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
            except ValueError:
                pass
        if data.get("end_date"):
            try:
                lease_end = datetime.strptime(data["end_date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        lease_doc = LeaseDocument(
            property_id=builder.property_id,
            tenant_id=builder.tenant_id,
            title=f"Michigan Lease - {prop.address if prop else 'Unknown'}",
            file_url=pdf_result["file_url"],
            file_type="pdf",
            file_size=pdf_result["file_size"],
            lease_start=lease_start,
            lease_end=lease_end,
            monthly_rent=data.get("monthly_rent"),
            status=LeaseStatus.ACTIVE,
        )
        session.add(lease_doc)
        await session.flush()

        builder.lease_document_id = lease_doc.id
        builder.status = LeaseBuilderStatus.GENERATED
        builder.generated_at = datetime.utcnow()

    return RedirectResponse(url=f"/leases/{lease_doc.id}", status_code=303)


@router.post("/{builder_id}/delete")
async def builder_delete(request: Request, builder_id: int):
    """Delete draft."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(LeaseBuilder).where(LeaseBuilder.id == builder_id)
        )
        builder = result.scalar_one_or_none()
        if builder:
            await session.delete(builder)

    return RedirectResponse(url="/leases/builder", status_code=303)
