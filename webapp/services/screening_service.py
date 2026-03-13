"""TenantReportX screening API wrapper using aiohttp"""

import logging
from datetime import datetime

import aiohttp
from sqlalchemy import select

from database.connection import get_session
from database.models import TenantApplication, ApplicationStatus
from webapp.config import web_config

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return web_config.tenantreportx_api_url.rstrip("/")


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {web_config.tenantreportx_api_key}",
        "X-Account-Id": web_config.tenantreportx_account_id,
    }


async def submit_screening(application_id: int) -> dict:
    """Submit applicant data to TenantReportX for screening.

    Creates an order via TenantReportX API, stores the order ID,
    and sets application status to SCREENING.
    """
    if not web_config.has_tenantreportx:
        logger.info("TenantReportX not configured — skipping screening submission")
        return {"skipped": True}

    async with get_session() as session:
        result = await session.execute(
            select(TenantApplication).where(TenantApplication.id == application_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            return {"error": "Application not found"}

        # TODO: Confirm exact endpoint path and field names with TenantReportX API docs
        url = f"{_base_url()}/v1/orders"
        payload = {
            "first_name": app.applicant_first_name,
            "last_name": app.applicant_last_name,
            "email": app.applicant_email,
            "phone": app.applicant_phone or "",
            "current_address": app.applicant_current_address or "",
            "employer": app.applicant_employer or "",
            "monthly_income": str(app.applicant_income or 0),
            "property_address": "",  # Filled below
            "products": ["credit", "criminal", "eviction"],
        }

        # Get property address
        if app.property_ref:
            payload["property_address"] = app.property_ref.address or ""

        try:
            async with aiohttp.ClientSession() as http:
                async with http.post(url, json=payload, headers=_headers()) as resp:
                    data = await resp.json()
                    if resp.status not in (200, 201):
                        logger.error(f"TenantReportX order create failed: {data}")
                        return {"error": data.get("message", "Screening submission failed")}

                    # TODO: Confirm response field names
                    order_id = data.get("order_id") or data.get("id")
                    app.trx_order_id = str(order_id)
                    app.trx_status = "submitted"
                    app.status = ApplicationStatus.SCREENING.value

                    return {"order_id": order_id}
        except Exception as e:
            logger.error(f"TenantReportX API error: {e}")
            return {"error": str(e)}


async def check_screening_status(trx_order_id: str) -> dict:
    """Check the status of a screening order.

    Returns the current status and any available results.
    """
    if not web_config.has_tenantreportx:
        return {"skipped": True}

    # TODO: Confirm exact endpoint path with TenantReportX API docs
    url = f"{_base_url()}/v1/orders/{trx_order_id}"

    try:
        async with aiohttp.ClientSession() as http:
            async with http.get(url, headers=_headers()) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"TenantReportX status check failed: {data}")
                    return {"error": data.get("message", "Status check failed")}
                return data
    except Exception as e:
        logger.error(f"TenantReportX API error: {e}")
        return {"error": str(e)}


async def process_webhook(payload: dict) -> dict:
    """Process a TenantReportX webhook callback.

    Looks up application by trx_order_id, updates screening results.
    """
    # TODO: Confirm exact webhook payload field names with TenantReportX docs
    order_id = str(payload.get("order_id") or payload.get("id", ""))
    if not order_id:
        return {"error": "No order_id in webhook payload"}

    async with get_session() as session:
        result = await session.execute(
            select(TenantApplication).where(TenantApplication.trx_order_id == order_id)
        )
        app = result.scalar_one_or_none()
        if not app:
            logger.warning(f"Webhook received for unknown order: {order_id}")
            return {"error": "Application not found"}

        # Update screening results
        app.trx_status = payload.get("status", "completed")
        app.credit_score = payload.get("credit_score")
        app.criminal_records_found = payload.get("criminal_records_found", False)
        app.eviction_records_found = payload.get("eviction_records_found", False)
        app.screening_recommendation = payload.get("recommendation", "")
        app.trx_report_url = payload.get("report_url", "")
        app.status = ApplicationStatus.COMPLETED.value
        app.screened_at = datetime.utcnow()

        logger.info(f"Screening completed for application {app.id} (order {order_id})")
        return {"success": True, "application_id": app.id}
