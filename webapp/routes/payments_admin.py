"""Admin Payment routes — view all payments, detail, Plaid webhook, Stripe webhook"""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import (
    RentPayment, PaymentStatus, Property, Tenant,
    StripePayment, WaterBill, BillStatus,
)
from webapp.auth.dependencies import get_current_user
from webapp.services import payment_service
from webapp.services import stripe_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments-admin"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
async def payments_list(
    request: Request,
    status: str = None,
    property_id: int = None,
    month: str = None,
    method: str = None,
):
    """All payments list with filters (ACH + Stripe)."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

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
        if status:
            ach_query = ach_query.where(RentPayment.status == PaymentStatus(status))
        if property_id:
            ach_query = ach_query.where(RentPayment.property_id == property_id)
        ach_query = ach_query.order_by(desc(RentPayment.initiated_at))

        # --- Stripe payments ---
        stripe_query = (
            select(StripePayment)
            .options(
                selectinload(StripePayment.tenant_ref),
                selectinload(StripePayment.property_ref),
            )
        )
        if status:
            stripe_query = stripe_query.where(StripePayment.status == PaymentStatus(status))
        if property_id:
            stripe_query = stripe_query.where(StripePayment.property_id == property_id)
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
                "detail_url": f"/payments/{p.id}",
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

    return templates.TemplateResponse(
        "payments/list.html",
        {
            "request": request,
            "user": user,
            "payments": all_payments,
            "properties": properties,
            "total_amount": total_amount,
            "completed_amount": completed_amount,
            "pending_count": pending_count,
            "entity_summary": entity_summary,
            "filter_status": status,
            "filter_property_id": property_id,
            "filter_method": method,
            "statuses": PaymentStatus,
        },
    )


@router.get("/{payment_id}", response_class=HTMLResponse)
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


@router.post("/webhook")
async def plaid_webhook(request: Request):
    """Plaid webhook endpoint (public, no auth)."""
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    result = await payment_service.process_webhook(data)
    return JSONResponse(result)


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

    if event_type == "checkout.session.completed":
        session_id = data_object.get("id")
        payment_intent = data_object.get("payment_intent")
        metadata = data_object.get("metadata", {})

        async with get_session() as session:
            result = await session.execute(
                select(StripePayment)
                .where(StripePayment.stripe_checkout_session_id == session_id)
            )
            sp = result.scalar_one_or_none()
            if sp:
                sp.status = PaymentStatus.COMPLETED
                sp.stripe_payment_intent_id = payment_intent
                sp.completed_at = datetime.utcnow()

                # If water bill payment, mark the bill as paid
                if sp.payment_type.value == "water_bill" and sp.reference_id:
                    bill_result = await session.execute(
                        select(WaterBill).where(WaterBill.id == sp.reference_id)
                    )
                    bill = bill_result.scalar_one_or_none()
                    if bill:
                        bill.amount_due = 0
                        bill.status = BillStatus.PAID

                logger.info(f"Stripe payment {sp.id} completed (session={session_id})")

    elif event_type == "checkout.session.expired":
        session_id = data_object.get("id")
        async with get_session() as session:
            result = await session.execute(
                select(StripePayment)
                .where(StripePayment.stripe_checkout_session_id == session_id)
            )
            sp = result.scalar_one_or_none()
            if sp:
                sp.status = PaymentStatus.CANCELLED
                sp.failed_at = datetime.utcnow()
                sp.failure_reason = "Checkout session expired"
                logger.info(f"Stripe payment {sp.id} expired (session={session_id})")

    return JSONResponse({"received": True})
