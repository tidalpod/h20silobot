"""Admin Payment routes — view all payments, detail, Plaid webhook, Stripe webhook"""

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload
from dateutil.relativedelta import relativedelta

from database.connection import get_session
from database.models import (
    RentPayment, PaymentStatus, Property, Tenant,
    StripePayment, WaterBill, BillStatus,
    TenantApplication, ApplicationStatus,
    TenantCharge, TenantLedgerEntry,
)
from webapp.auth.dependencies import get_current_user
from webapp.services import payment_service
from webapp.services import stripe_service
from webapp.services import ledger_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments-admin"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def payments_list(
    request: Request,
    status: str = None,
    property_id: str = "",
    tenant_id: str = "",
    month: str = None,
    method: str = None,
    page: int = 1,
    page_size: int = 25,
):
    """All payments list with filters (ACH + Stripe)."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        selected_status = PaymentStatus(status) if status else None
    except ValueError:
        selected_status = None
        status = None

    if method not in {None, "", "ach", "card"}:
        method = None

    page = max(page, 1)
    page_size = page_size if page_size in {25, 50, 100} else 25
    try:
        selected_property_id = int(property_id) if property_id.strip() else None
    except (TypeError, ValueError):
        selected_property_id = None
    try:
        selected_tenant_id = int(tenant_id) if tenant_id.strip() else None
    except (TypeError, ValueError):
        selected_tenant_id = None

    async with get_session() as session:
        # --- ACH payments ---
        ach_query = (
            select(RentPayment)
            .options(
                selectinload(RentPayment.tenant_ref),
                selectinload(RentPayment.property_ref),
                selectinload(RentPayment.bank_account_ref),
            )
        )
        if selected_status:
            ach_query = ach_query.where(RentPayment.status == selected_status)
        if selected_property_id:
            ach_query = ach_query.where(RentPayment.property_id == selected_property_id)
        if selected_tenant_id:
            ach_query = ach_query.where(RentPayment.tenant_id == selected_tenant_id)
        ach_query = ach_query.order_by(desc(RentPayment.initiated_at))

        # --- Stripe payments ---
        stripe_query = (
            select(StripePayment)
            .options(
                selectinload(StripePayment.tenant_ref),
                selectinload(StripePayment.property_ref),
            )
        )
        if selected_status:
            stripe_query = stripe_query.where(StripePayment.status == selected_status)
        if selected_property_id:
            stripe_query = stripe_query.where(StripePayment.property_id == selected_property_id)
        if selected_tenant_id:
            stripe_query = stripe_query.where(StripePayment.tenant_id == selected_tenant_id)
        stripe_query = stripe_query.order_by(desc(StripePayment.initiated_at))

        # Execute both (skip one if method filter applied)
        ach_payments = []
        stripe_payments = []
        if method != "card":
            ach_result = await session.execute(ach_query)
            ach_payments = ach_result.scalars().all()
        if method != "ach":
            stripe_result = await session.execute(stripe_query)
            stripe_payments = stripe_result.scalars().all()

        # Merge into unified dicts
        all_payments = []
        for p in ach_payments:
            all_payments.append({
                "id": p.id,
                "method": "ach",
                "tenant_name": p.tenant_ref.name if p.tenant_ref else "—",
                "property_address": p.property_ref.address if p.property_ref else "—",
                "entity": p.property_ref.entity if p.property_ref and p.property_ref.entity else "Unassigned",
                "description": f"Rent - {p.payment_month.strftime('%b %Y')}" if p.payment_month else "Rent",
                "payment_month": p.payment_month,
                "total_amount": float(p.total_amount or 0),
                "late_fee": float(p.late_fee or 0),
                "convenience_fee": 0,
                "status": p.status,
                "initiated_at": p.initiated_at,
                "is_autopay": p.is_autopay,
                "detail_url": f"/payments/ach/{p.id}",
            })
        for p in stripe_payments:
            all_payments.append({
                "id": p.id,
                "method": "card",
                "tenant_name": p.tenant_ref.name if p.tenant_ref else "—",
                "property_address": p.property_ref.address if p.property_ref else "—",
                "entity": p.property_ref.entity if p.property_ref and p.property_ref.entity else "Unassigned",
                "description": p.description,
                "payment_month": p.payment_month,
                "total_amount": float(p.total_amount or 0),
                "late_fee": float(p.late_fee or 0),
                "convenience_fee": float(p.convenience_fee or 0),
                "status": p.status,
                "initiated_at": p.initiated_at,
                "is_autopay": False,
                "detail_url": None,
            })

        # Sort merged list by date desc
        all_payments.sort(key=lambda x: x["initiated_at"] or datetime.min, reverse=True)

        # Totals
        total_amount = sum(p["total_amount"] for p in all_payments)
        completed_amount = sum(
            p["total_amount"] for p in all_payments
            if p["status"] == PaymentStatus.COMPLETED
        )
        pending_count = sum(1 for p in all_payments if p["status"] in (PaymentStatus.PENDING, PaymentStatus.PROCESSING))

        # Entity breakdown
        entity_summary = {}
        for p in all_payments:
            entity_name = p["entity"]
            if entity_name not in entity_summary:
                entity_summary[entity_name] = {"collected": 0.0, "pending": 0.0, "count": 0}
            if p["status"] == PaymentStatus.COMPLETED:
                entity_summary[entity_name]["collected"] += p["total_amount"]
            elif p["status"] in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
                entity_summary[entity_name]["pending"] += p["total_amount"]
            entity_summary[entity_name]["count"] += 1
        entity_summary = dict(sorted(entity_summary.items(), key=lambda x: x[1]["collected"], reverse=True))

        # Properties for filter dropdown
        props_result = await session.execute(
            select(Property).where(Property.is_active == True).order_by(Property.address)
        )
        properties = props_result.scalars().all()

        tenant_query = (
            select(Tenant)
            .where(Tenant.is_active == True)
            .options(selectinload(Tenant.property_ref))
            .order_by(Tenant.name)
        )
        if selected_property_id:
            tenant_query = tenant_query.where(Tenant.property_id == selected_property_id)
        tenants_result = await session.execute(tenant_query)
        tenants = tenants_result.scalars().all()

    charges = await ledger_service.list_charges(
        tenant_id=selected_tenant_id,
        property_id=selected_property_id,
        include_paid=True,
    )
    charge_totals = ledger_service.totals(charges)
    selected_tenant = next((tenant for tenant in tenants if tenant.id == selected_tenant_id), None)
    selected_property = next((prop for prop in properties if prop.id == selected_property_id), None)

    total_items = len(all_payments)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = min(page, total_pages)
    all_payments = all_payments[(page - 1) * page_size:page * page_size]
    pagination_params = {
        "status": status or "",
        "property_id": selected_property_id or "",
        "tenant_id": selected_tenant_id or "",
        "method": method or "",
    }
    pagination_base = f"/payments?{urlencode(pagination_params)}&"

    return templates.TemplateResponse(
        "payments/list.html",
        {
            "request": request,
            "user": user,
            "payments": all_payments,
            "properties": properties,
            "tenants": tenants,
            "charges": charges,
            "charge_totals": charge_totals,
            "selected_tenant": selected_tenant,
            "selected_property": selected_property,
            "total_amount": total_amount,
            "completed_amount": completed_amount,
            "pending_count": pending_count,
            "entity_summary": entity_summary,
            "filter_status": status,
            "filter_property_id": selected_property_id,
            "filter_tenant_id": selected_tenant_id,
            "filter_method": method,
            "statuses": PaymentStatus,
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "pagination_base": pagination_base,
        },
    )


def _ledger_redirect(form, *, success: str | None = None, error: str | None = None):
    params = {}
    for key in ("property_id", "tenant_id"):
        value = form.get(key)
        if value and str(value).isdigit():
            params[key] = value
    if success:
        params["success"] = success
    if error:
        params["error"] = error
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/payments{query}", status_code=303)


def _parse_date(value: str | None, fallback: date | None = None) -> date | None:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


@router.post("/charges")
async def create_charge(request: Request):
    """Create one charge or a bounded monthly series."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    try:
        tenant_id = int(form.get("tenant_id", 0))
        amount = ledger_service.money(Decimal(str(form.get("amount", "0"))))
    except (ValueError, InvalidOperation):
        return _ledger_redirect(form, error="invalid_charge")

    due_date = _parse_date(form.get("due_date"))
    description = str(form.get("description", "")).strip()
    charge_type = str(form.get("charge_type", "other")).strip() or "other"
    if not tenant_id or not due_date or amount <= 0 or not description:
        return _ledger_redirect(form, error="invalid_charge")

    repeat_monthly = form.get("repeat_monthly") == "on"
    end_date = _parse_date(form.get("end_date"), due_date)
    if not repeat_monthly:
        end_date = due_date
    if end_date < due_date:
        return _ledger_redirect(form, error="invalid_end_date")

    async with get_session() as session:
        tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one_or_none()
        if not tenant:
            return _ledger_redirect(form, error="tenant_not_found")

        recurrence_group = uuid.uuid4().hex if repeat_monthly else None
        cursor = due_date
        created = 0
        while cursor <= end_date and created < 36:
            label = description
            if repeat_monthly:
                label = f"{description} — {cursor.strftime('%B %Y')}"
            session.add(TenantCharge(
                tenant_id=tenant.id,
                property_id=tenant.property_id,
                charge_type=charge_type,
                description=label,
                amount=amount,
                due_date=cursor,
                service_start=cursor.replace(day=1) if repeat_monthly else None,
                is_recurring=repeat_monthly,
                recurrence_group=recurrence_group,
                created_by_user_id=user["id"],
            ))
            created += 1
            cursor += relativedelta(months=1)

    return _ledger_redirect(form, success="charge_created")


@router.post("/entries")
async def create_ledger_entry(request: Request):
    """Record an offline payment, credit, or returned security deposit."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    entry_type = str(form.get("entry_type", "payment"))
    if entry_type not in {"payment", "credit", "refund"}:
        return _ledger_redirect(form, error="invalid_activity")

    try:
        charge_value = str(form.get("charge_id", "")).strip()
        tenant_value = str(form.get("tenant_id", "")).strip()
        charge_id = int(charge_value) if charge_value else None
        tenant_id = int(tenant_value) if tenant_value else 0
        amount = ledger_service.money(Decimal(str(form.get("amount", "0"))))
    except (ValueError, InvalidOperation):
        return _ledger_redirect(form, error="invalid_activity")

    charge = await ledger_service.get_charge(charge_id) if charge_id else None
    if entry_type in {"payment", "credit"} and not charge:
        return _ledger_redirect(form, error="charge_required")
    if charge:
        tenant_id = charge["tenant_id"]
        property_id = charge["property_id"]
        if entry_type in {"payment", "credit"} and amount > charge["outstanding"]:
            return _ledger_redirect(form, error="amount_too_high")
    else:
        async with get_session() as session:
            tenant_result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            tenant = tenant_result.scalar_one_or_none()
            if not tenant:
                return _ledger_redirect(form, error="tenant_not_found")
            property_id = tenant.property_id

    if amount <= 0:
        return _ledger_redirect(form, error="invalid_activity")

    labels = {
        "payment": "Recorded payment",
        "credit": "Account credit",
        "refund": "Security deposit returned",
    }
    async with get_session() as session:
        session.add(TenantLedgerEntry(
            tenant_id=tenant_id,
            property_id=property_id,
            charge_id=charge_id,
            entry_type=entry_type,
            amount=amount,
            status="posted",
            payment_method=str(form.get("payment_method", "manual")),
            description=str(form.get("description", "")).strip() or labels[entry_type],
            note=str(form.get("note", "")).strip() or None,
            external_provider="manual",
            external_id=uuid.uuid4().hex,
            occurred_on=_parse_date(form.get("occurred_on"), date.today()),
            created_by_user_id=user["id"],
        ))

    return _ledger_redirect(form, success=f"{entry_type}_recorded")


@router.post("/charges/{charge_id}/edit")
async def edit_charge(request: Request, charge_id: int):
    """Edit a charge without allowing its total below already-applied money."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()

    try:
        amount = ledger_service.money(Decimal(str(form.get("amount", "0"))))
    except (ValueError, InvalidOperation):
        return _ledger_redirect(form, error="invalid_charge")
    due_date = _parse_date(form.get("due_date"))
    description = str(form.get("description", "")).strip()

    async with get_session() as session:
        result = await session.execute(
            select(TenantCharge)
            .where(TenantCharge.id == charge_id)
            .options(selectinload(TenantCharge.ledger_entries))
        )
        charge = result.scalar_one_or_none()
        if not charge:
            return _ledger_redirect(form, error="charge_not_found")
        applied = ledger_service.charge_snapshot(charge)["applied"]
        if amount < applied or amount <= 0 or not due_date or not description:
            return _ledger_redirect(form, error="amount_below_paid")
        charge.amount = amount
        charge.description = description
        charge.due_date = due_date
        charge.charge_type = str(form.get("charge_type", charge.charge_type))
        charge.updated_at = datetime.utcnow()

    return _ledger_redirect(form, success="charge_updated")


@router.get("/ach/{payment_id}", response_class=HTMLResponse)
async def payment_detail(request: Request, payment_id: int):
    """Single payment detail."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    async with get_session() as session:
        result = await session.execute(
            select(RentPayment)
            .where(RentPayment.id == payment_id)
            .options(
                selectinload(RentPayment.tenant_ref),
                selectinload(RentPayment.property_ref),
                selectinload(RentPayment.bank_account_ref),
            )
        )
        payment = result.scalar_one_or_none()
        if not payment:
            return RedirectResponse(url="/payments", status_code=303)

    return templates.TemplateResponse(
        "payments/detail.html",
        {"request": request, "user": user, "payment": payment},
    )


@router.post("/webhooks/plaid")
@router.post("/webhook")
async def plaid_webhook(request: Request):
    """Plaid webhook endpoint (public, no auth)."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    result = await payment_service.process_webhook(data)
    return JSONResponse(result)


@router.post("/webhooks/stripe")
@router.post("/stripe-webhook")
async def stripe_webhook(request: Request):
    """Stripe webhook endpoint (public, no auth, signature-verified)."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    event = stripe_service.verify_webhook_signature(payload, sig_header)
    if not event:
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    event_type = event.get("type", "")
    data_object = event.get("data", {}).get("object", {})

    if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        session_id = data_object.get("id")
        payment_intent = data_object.get("payment_intent")
        metadata = data_object.get("metadata", {})
        payment_status = data_object.get("payment_status")
        is_paid = payment_status == "paid" or event_type == "checkout.session.async_payment_succeeded"
        stripe_payment_data = None

        async with get_session() as session:
            result = await session.execute(
                select(StripePayment)
                .where(StripePayment.stripe_checkout_session_id == session_id)
            )
            sp = result.scalar_one_or_none()
            if sp:
                sp.status = PaymentStatus.COMPLETED if is_paid else PaymentStatus.PROCESSING
                sp.stripe_payment_intent_id = payment_intent
                if is_paid:
                    sp.completed_at = sp.completed_at or datetime.utcnow()

                # If water bill payment, mark the bill as paid
                if is_paid and sp.payment_type.value == "water_bill" and sp.reference_id:
                    bill_result = await session.execute(
                        select(WaterBill).where(WaterBill.id == sp.reference_id)
                    )
                    bill = bill_result.scalar_one_or_none()
                    if bill:
                        bill.amount_due = 0
                        bill.status = BillStatus.PAID

                stripe_payment_data = {
                    "charge_id": sp.charge_id,
                    "tenant_id": sp.tenant_id,
                    "property_id": sp.property_id,
                    "amount": max(Decimal(str(sp.base_amount or 0)) - Decimal(str(sp.late_fee or 0)), Decimal("0.00")),
                    "description": sp.description,
                }
                logger.info(f"Stripe payment {sp.id} updated (session={session_id}, paid={is_paid})")

        if is_paid and stripe_payment_data:
            await ledger_service.post_external_payment(
                provider="stripe",
                external_id=session_id,
                charge_id=stripe_payment_data["charge_id"],
                tenant_id=stripe_payment_data["tenant_id"],
                property_id=stripe_payment_data["property_id"],
                amount=stripe_payment_data["amount"],
                payment_method="card",
                description=stripe_payment_data["description"],
            )

        # --- Application fee payments ---
        if is_paid and metadata.get("type") == "application_fee":
            app_id_str = metadata.get("application_id")
            if app_id_str:
                async with get_session() as session:
                    result = await session.execute(
                        select(TenantApplication)
                        .where(TenantApplication.id == int(app_id_str))
                        .options(selectinload(TenantApplication.property_ref))
                    )
                    application = result.scalar_one_or_none()
                    if application and application.status == ApplicationStatus.PENDING_PAYMENT.value:
                        application.status = ApplicationStatus.PENDING.value
                        prop = application.property_ref
                        logger.info(f"Application {app_id_str} activated via webhook (session={session_id})")

                        # Submit screening if configured
                        from webapp.config import web_config
                        if web_config.has_tenantreportx:
                            try:
                                from webapp.services.screening_service import submit_screening
                                await submit_screening(application.id)
                            except Exception as e:
                                logger.error(f"Screening submission failed (webhook): {e}")

                        # Send Telegram notification
                        try:
                            from webapp.routes.applications import _send_application_telegram
                            await _send_application_telegram(application, prop)
                        except Exception as e:
                            logger.error(f"Telegram notification failed (webhook): {e}")

    elif event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        session_id = data_object.get("id")
        async with get_session() as session:
            result = await session.execute(
                select(StripePayment)
                .where(StripePayment.stripe_checkout_session_id == session_id)
            )
            sp = result.scalar_one_or_none()
            if sp:
                sp.status = PaymentStatus.CANCELLED if event_type == "checkout.session.expired" else PaymentStatus.FAILED
                sp.failed_at = datetime.utcnow()
                sp.failure_reason = "Checkout session expired" if event_type == "checkout.session.expired" else "Card payment failed"
                logger.info(f"Stripe payment {sp.id} failed or expired (session={session_id})")

    return JSONResponse({"received": True})


@router.get("/{payment_id}", response_class=HTMLResponse, include_in_schema=False)
async def legacy_payment_detail(request: Request, payment_id: int):
    """Keep existing ACH detail links working without shadowing webhook routes."""
    return await payment_detail(request, payment_id)
