"""Stripe Checkout service — session creation, fee calculation, webhook verification"""

import logging
from decimal import Decimal, ROUND_HALF_UP

import stripe

from webapp.config import web_config

logger = logging.getLogger(__name__)

# Convenience fee: 2.9% + $0.30
FEE_RATE = Decimal("0.029")
FEE_FIXED = Decimal("0.30")


def _init_stripe():
    """Set Stripe API key from config."""
    stripe.api_key = web_config.stripe_secret_key


def calculate_convenience_fee(base_amount: Decimal) -> dict:
    """Calculate convenience fee for card payment.

    Returns dict with base_amount, convenience_fee, total_amount (all Decimal).
    """
    base = Decimal(str(base_amount))
    fee = (base * FEE_RATE + FEE_FIXED).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = base + fee
    return {
        "base_amount": base,
        "convenience_fee": fee,
        "total_amount": total,
    }


def create_checkout_session(
    *,
    base_amount: Decimal,
    convenience_fee: Decimal,
    description: str,
    success_url: str,
    cancel_url: str,
    metadata: dict,
) -> dict:
    """Create a Stripe Checkout Session with two line items.

    Returns {session_id, url} on success or {error} on failure.
    """
    _init_stripe()

    base_cents = int(Decimal(str(base_amount)) * 100)
    fee_cents = int(Decimal(str(convenience_fee)) * 100)

    line_items = [
        {
            "price_data": {
                "currency": "usd",
                "product_data": {"name": description},
                "unit_amount": base_cents,
            },
            "quantity": 1,
        },
    ]

    if fee_cents > 0:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Card Processing Fee"},
                "unit_amount": fee_cents,
            },
            "quantity": 1,
        })

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
        )
        return {"session_id": session.id, "url": session.url}
    except stripe.StripeError as e:
        logger.error(f"Stripe Checkout error: {e}")
        return {"error": str(e)}


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict | None:
    """Verify Stripe webhook signature and return parsed event, or None."""
    _init_stripe()
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, web_config.stripe_webhook_secret
        )
        return event
    except (stripe.SignatureVerificationError, ValueError) as e:
        logger.warning(f"Stripe webhook signature verification failed: {e}")
        return None


def retrieve_session(session_id: str) -> dict | None:
    """Retrieve a Checkout Session by ID for success page verification."""
    _init_stripe()
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            "id": session.id,
            "payment_status": session.payment_status,
            "payment_intent": session.payment_intent,
            "amount_total": session.amount_total,
            "metadata": dict(session.metadata) if session.metadata else {},
        }
    except stripe.StripeError as e:
        logger.error(f"Stripe session retrieve error: {e}")
        return None
