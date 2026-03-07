"""Public e-signature routes — no login required, token-secured."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import ESignSigner, ESignEnvelope, ESignStatus, LeaseDocument
from webapp.services import esign_service

router = APIRouter(tags=["esign-public"])
logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.get("/sign/{token}", response_class=HTMLResponse)
async def signing_page(request: Request, token: str):
    """Public signing page — shows lease preview + signature capture."""
    data = esign_service.verify_signing_token(token)
    if not data:
        return templates.TemplateResponse("leases/esign_expired.html", {"request": request})

    signer_id = data["sid"]
    envelope_id = data["eid"]

    async with get_session() as session:
        # Load signer
        result = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = result.scalar_one_or_none()
        if not signer:
            return templates.TemplateResponse("leases/esign_expired.html", {"request": request})

        # Already signed?
        if signer.status == "signed":
            return templates.TemplateResponse("leases/esign_complete.html", {
                "request": request,
                "signer": signer,
                "already_signed": True,
            })

        # Already declined?
        if signer.status == "declined":
            return templates.TemplateResponse("leases/esign_declined.html", {
                "request": request,
                "signer": signer,
            })

        # Load envelope
        env_result = await session.execute(
            select(ESignEnvelope).where(ESignEnvelope.id == envelope_id)
        )
        envelope = env_result.scalar_one_or_none()
        if not envelope or envelope.status in (ESignStatus.VOIDED, ESignStatus.COMPLETED):
            return templates.TemplateResponse("leases/esign_expired.html", {"request": request})

        # Load lease for preview
        lease_result = await session.execute(
            select(LeaseDocument)
            .where(LeaseDocument.id == envelope.lease_document_id)
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
        )
        lease = lease_result.scalar_one_or_none()

        # Record view
        await esign_service.record_view(
            signer_id, _client_ip(request),
            request.headers.get("user-agent", "")
        )

    property_address = ""
    if lease and lease.property_ref:
        p = lease.property_ref
        property_address = f"{p.address}, {p.city}, {p.state} {p.zip_code}"

    return templates.TemplateResponse("leases/esign_sign.html", {
        "request": request,
        "signer": signer,
        "lease": lease,
        "property_address": property_address,
        "token": token,
    })


@router.post("/sign/{token}", response_class=HTMLResponse)
async def submit_signing(request: Request, token: str):
    """Process signature submission."""
    data = esign_service.verify_signing_token(token)
    if not data:
        return templates.TemplateResponse("leases/esign_expired.html", {"request": request})

    signer_id = data["sid"]
    form = await request.form()
    signature_data = form.get("signature_data", "")
    signature_type = form.get("signature_type", "draw")

    if not signature_data:
        # Redirect back with error
        return RedirectResponse(url=f"/sign/{token}?error=no_signature", status_code=303)

    result = await esign_service.submit_signature(
        signer_id=signer_id,
        signature_data_base64=signature_data,
        signature_type=signature_type,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )

    if "error" in result:
        return RedirectResponse(url=f"/sign/{token}?error={result['error'][:80]}", status_code=303)

    # Load signer for confirmation page
    async with get_session() as session:
        sr = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = sr.scalar_one_or_none()

    return templates.TemplateResponse("leases/esign_complete.html", {
        "request": request,
        "signer": signer,
        "all_complete": result.get("all_complete", False),
    })


@router.post("/sign/{token}/decline", response_class=HTMLResponse)
async def decline_signing(request: Request, token: str):
    """Decline to sign."""
    data = esign_service.verify_signing_token(token)
    if not data:
        return templates.TemplateResponse("leases/esign_expired.html", {"request": request})

    signer_id = data["sid"]
    form = await request.form()
    reason = form.get("reason", "")

    result = await esign_service.decline_signature(
        signer_id=signer_id,
        reason=reason,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )

    async with get_session() as session:
        sr = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = sr.scalar_one_or_none()

    return templates.TemplateResponse("leases/esign_declined.html", {
        "request": request,
        "signer": signer,
    })
