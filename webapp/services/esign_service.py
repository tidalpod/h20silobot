"""In-house e-signature service.

Replaces DocuSign with token-based email links, canvas signature capture,
and WeasyPrint PDF generation with embedded signatures.
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from webapp.config import web_config

logger = logging.getLogger(__name__)

# Upload paths
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
SIGNATURES_DIR = Path(UPLOAD_BASE) / "leases" / "signatures"
SIGNATURES_DIR.mkdir(parents=True, exist_ok=True)
SIGNED_DIR = Path(UPLOAD_BASE) / "leases" / "signed"
SIGNED_DIR.mkdir(parents=True, exist_ok=True)

# Token serializer (7-day expiry)
TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 days in seconds
_serializer = URLSafeTimedSerializer(web_config.secret_key, salt="esign-v1")


# =============================================================================
# Token Management
# =============================================================================

def generate_signing_token(signer_id: int, envelope_id: int) -> str:
    """Generate a secure, time-limited signing token."""
    return _serializer.dumps({"sid": signer_id, "eid": envelope_id})


def verify_signing_token(token: str, max_age: int = TOKEN_MAX_AGE) -> Optional[dict]:
    """Verify a signing token. Returns {"sid": ..., "eid": ...} or None."""
    try:
        data = _serializer.loads(token, max_age=max_age)
        return data
    except (BadSignature, SignatureExpired):
        return None


# =============================================================================
# Audit Logging
# =============================================================================

async def _log_audit(session, envelope_id: int, action: str,
                     signer_id: int = None, details: dict = None,
                     ip: str = None, user_agent: str = None):
    """Write an audit log entry."""
    from database.models import ESignAuditLog
    log = ESignAuditLog(
        envelope_id=envelope_id,
        signer_id=signer_id,
        action=action,
        details=json.dumps(details) if details else None,
        ip_address=ip,
        user_agent=user_agent,
    )
    session.add(log)


# =============================================================================
# Envelope Lifecycle
# =============================================================================

async def create_signing_request(lease_document_id: int, signers: list[dict]) -> dict:
    """
    Create an envelope + signer rows, send signing emails, log audit.

    signers: [{"name": "...", "email": "...", "role": "tenant|landlord|cosigner"}, ...]
    Returns {"envelope_id": int, "status": "sent"} or {"error": "..."}
    """
    from database.connection import get_session
    from database.models import ESignEnvelope, ESignSigner, ESignStatus, LeaseDocument
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_session() as session:
        # Load lease + property for email context
        result = await session.execute(
            select(LeaseDocument)
            .where(LeaseDocument.id == lease_document_id)
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
        )
        lease = result.scalar_one_or_none()
        if not lease:
            return {"error": "Lease document not found"}

        # Create envelope
        envelope = ESignEnvelope(
            lease_document_id=lease_document_id,
            signing_mode="inhouse",
            status=ESignStatus.SENT,
            sent_at=datetime.utcnow(),
        )
        session.add(envelope)
        await session.flush()  # get envelope.id

        await _log_audit(session, envelope.id, "envelope_created",
                         details={"signers": [s["email"] for s in signers]})

        # Assign signing order: tenants=1, cosigners=1, landlords=2
        for signer_data in signers:
            role = signer_data.get("role", "tenant")
            order = 2 if role == "landlord" else 1
            signer = ESignSigner(
                envelope_id=envelope.id,
                name=signer_data["name"],
                email=signer_data["email"],
                role=role,
                signing_order=order,
                status="pending" if order == 1 else "waiting",
            )
            session.add(signer)
            await session.flush()

            # Only send email to order=1 signers now; order=2 wait
            if order == 1:
                token = generate_signing_token(signer.id, envelope.id)
                await _send_signing_email(signer, envelope, lease, token)
                await _log_audit(session, envelope.id, "email_sent",
                                 signer_id=signer.id,
                                 details={"email": signer.email})
            else:
                await _log_audit(session, envelope.id, "signer_queued",
                                 signer_id=signer.id,
                                 details={"email": signer.email, "order": order})

        return {"envelope_id": envelope.id, "status": "sent"}


async def void_envelope(envelope_id: int, reason: str = "") -> dict:
    """Void an envelope — cancel all pending signatures."""
    from database.connection import get_session
    from database.models import ESignEnvelope, ESignStatus
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(ESignEnvelope).where(ESignEnvelope.id == envelope_id)
        )
        envelope = result.scalar_one_or_none()
        if not envelope:
            return {"error": "Envelope not found"}

        envelope.status = ESignStatus.VOIDED
        envelope.void_reason = reason
        envelope.updated_at = datetime.utcnow()

        await _log_audit(session, envelope.id, "voided",
                         details={"reason": reason})

        return {"status": "voided"}


async def resend_signing_email(signer_id: int) -> dict:
    """Resend the signing email for a pending signer."""
    from database.connection import get_session
    from database.models import ESignSigner, ESignEnvelope, LeaseDocument
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_session() as session:
        result = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = result.scalar_one_or_none()
        if not signer or signer.status not in ("pending", "viewed"):
            return {"error": "Signer not found or already signed"}

        env_result = await session.execute(
            select(ESignEnvelope).where(ESignEnvelope.id == signer.envelope_id)
        )
        envelope = env_result.scalar_one_or_none()

        lease_result = await session.execute(
            select(LeaseDocument)
            .where(LeaseDocument.id == envelope.lease_document_id)
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
        )
        lease = lease_result.scalar_one_or_none()

        token = generate_signing_token(signer.id, envelope.id)
        await _send_signing_email(signer, envelope, lease, token)
        await _log_audit(session, envelope.id, "email_resent",
                         signer_id=signer.id,
                         details={"email": signer.email})

        return {"status": "resent"}


# =============================================================================
# Signing Actions
# =============================================================================

async def record_view(signer_id: int, ip: str = None, user_agent: str = None):
    """Mark a signer as having viewed the document."""
    from database.connection import get_session
    from database.models import ESignSigner
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = result.scalar_one_or_none()
        if not signer:
            return

        if signer.status == "pending":
            signer.status = "viewed"
            signer.viewed_at = datetime.utcnow()

        await _log_audit(session, signer.envelope_id, "link_opened",
                         signer_id=signer.id, ip=ip, user_agent=user_agent)


async def submit_signature(signer_id: int, signature_data_base64: str,
                           signature_type: str, ip: str = None,
                           user_agent: str = None) -> dict:
    """
    Process a signature submission.
    Saves the PNG, updates status, checks if all signed → triggers PDF + emails.
    """
    from database.connection import get_session
    from database.models import ESignSigner, ESignEnvelope, ESignStatus
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    async with get_session() as session:
        result = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = result.scalar_one_or_none()
        if not signer:
            return {"error": "Signer not found"}
        if signer.status == "signed":
            return {"error": "Already signed"}

        # Save signature PNG
        sig_filename = f"sig_{uuid.uuid4().hex[:12]}.png"
        sig_path = SIGNATURES_DIR / sig_filename
        try:
            # Handle data URL prefix if present
            if "," in signature_data_base64:
                signature_data_base64 = signature_data_base64.split(",", 1)[1]
            sig_bytes = base64.b64decode(signature_data_base64)
            with open(sig_path, "wb") as f:
                f.write(sig_bytes)
        except Exception as e:
            logger.error(f"Failed to save signature: {e}")
            return {"error": "Invalid signature data"}

        sig_url = f"/uploads/leases/signatures/{sig_filename}"

        # Update signer
        signer.status = "signed"
        signer.signed_at = datetime.utcnow()
        signer.signature_file_url = sig_url
        signer.signature_type = signature_type
        signer.ip_address = ip
        signer.user_agent = user_agent

        await _log_audit(session, signer.envelope_id, "signed",
                         signer_id=signer.id,
                         details={"signature_type": signature_type},
                         ip=ip, user_agent=user_agent)

        # Reload envelope with all signers
        env_result = await session.execute(
            select(ESignEnvelope)
            .where(ESignEnvelope.id == signer.envelope_id)
            .options(selectinload(ESignEnvelope.signer_records))
        )
        envelope = env_result.scalar_one_or_none()

        # Check if all signers at the current order level have signed
        current_order = signer.signing_order
        same_order_signers = [s for s in envelope.signer_records if s.signing_order == current_order]
        all_current_order_signed = all(s.status == "signed" for s in same_order_signers)

        if all_current_order_signed:
            # Activate next-order signers (send them emails)
            next_order_signers = [s for s in envelope.signer_records
                                  if s.signing_order == current_order + 1 and s.status == "waiting"]
            if next_order_signers:
                # Load lease for email context
                from database.models import LeaseDocument
                lease_result = await session.execute(
                    select(LeaseDocument)
                    .where(LeaseDocument.id == envelope.lease_document_id)
                    .options(
                        selectinload(LeaseDocument.property_ref),
                        selectinload(LeaseDocument.tenant_ref),
                    )
                )
                lease = lease_result.scalar_one_or_none()

                for next_signer in next_order_signers:
                    next_signer.status = "pending"
                    token = generate_signing_token(next_signer.id, envelope.id)
                    await _send_signing_email(next_signer, envelope, lease, token)
                    await _log_audit(session, envelope.id, "email_sent",
                                     signer_id=next_signer.id,
                                     details={"email": next_signer.email, "triggered_by": signer.name})
                    logger.info(f"[ESIGN] Sequential: sent signing email to {next_signer.name} (order {next_signer.signing_order})")

        # Check if ALL signers are done
        all_signed = all(s.status == "signed" for s in envelope.signer_records)

        if all_signed:
            envelope.status = ESignStatus.COMPLETED
            envelope.completed_at = datetime.utcnow()
            envelope.updated_at = datetime.utcnow()

            # Generate signed PDF
            logger.info(f"[ESIGN] Generating signed PDF for envelope {envelope.id}")
            try:
                pdf_result = await generate_signed_pdf(envelope.id, session=session)
                logger.info(f"[ESIGN] Signed PDF result: {pdf_result}")
                if "error" not in pdf_result:
                    envelope.signed_file_url = pdf_result.get("file_url")
                    await _log_audit(session, envelope.id, "pdf_generated",
                                     details={"file_url": pdf_result.get("file_url")})
                else:
                    logger.error(f"[ESIGN] Signed PDF generation failed: {pdf_result['error']}")
            except Exception as e:
                logger.error(f"[ESIGN] Exception generating signed PDF: {e}", exc_info=True)

            # Send completion emails
            await _send_completion_emails(envelope.id, session=session)

        return {"status": "signed", "all_complete": all_signed}


async def decline_signature(signer_id: int, reason: str = "",
                            ip: str = None, user_agent: str = None) -> dict:
    """Decline to sign."""
    from database.connection import get_session
    from database.models import ESignSigner, ESignEnvelope, ESignStatus
    from sqlalchemy import select

    async with get_session() as session:
        result = await session.execute(
            select(ESignSigner).where(ESignSigner.id == signer_id)
        )
        signer = result.scalar_one_or_none()
        if not signer:
            return {"error": "Signer not found"}

        signer.status = "declined"
        signer.declined_at = datetime.utcnow()
        signer.decline_reason = reason
        signer.ip_address = ip
        signer.user_agent = user_agent

        # Mark envelope as declined
        env_result = await session.execute(
            select(ESignEnvelope).where(ESignEnvelope.id == signer.envelope_id)
        )
        envelope = env_result.scalar_one_or_none()
        if envelope:
            envelope.status = ESignStatus.DECLINED
            envelope.updated_at = datetime.utcnow()

        await _log_audit(session, signer.envelope_id, "declined",
                         signer_id=signer.id,
                         details={"reason": reason},
                         ip=ip, user_agent=user_agent)

        # Notify admin
        await _send_decline_notification(signer, session=session)

        return {"status": "declined"}


# =============================================================================
# Signed PDF Generation
# =============================================================================

async def generate_signed_pdf(envelope_id: int, session=None) -> dict:
    """
    Generate a signed PDF with embedded signature images.

    For builder-generated leases: re-render HTML with signatures.
    For uploaded PDFs: generate a signature page and append via pypdf.
    """
    from database.models import ESignEnvelope, ESignSigner, LeaseDocument
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    own_session = session is None
    if own_session:
        from database.connection import get_session
        ctx = get_session()
        session = await ctx.__aenter__()

    try:
        result = await session.execute(
            select(ESignEnvelope)
            .where(ESignEnvelope.id == envelope_id)
            .options(selectinload(ESignEnvelope.signer_records))
        )
        envelope = result.scalar_one_or_none()
        if not envelope:
            return {"error": "Envelope not found"}

        lease_result = await session.execute(
            select(LeaseDocument)
            .where(LeaseDocument.id == envelope.lease_document_id)
            .options(
                selectinload(LeaseDocument.property_ref),
                selectinload(LeaseDocument.tenant_ref),
            )
        )
        lease = lease_result.scalar_one_or_none()
        if not lease:
            return {"error": "Lease document not found"}

        # Build signatures dict keyed by role
        signatures = {}
        for signer in envelope.signer_records:
            if signer.status == "signed" and signer.signature_file_url:
                sig_path = str(Path(UPLOAD_BASE) / signer.signature_file_url.removeprefix("/uploads/"))
                logger.info(f"[ESIGN] Signer {signer.name} sig path: {sig_path}, exists: {Path(sig_path).exists()}")
                signatures[f"{signer.role}_{signer.id}"] = {
                    "name": signer.name,
                    "email": signer.email,
                    "role": signer.role,
                    "image_path": sig_path,
                    "signed_at": signer.signed_at.strftime("%B %d, %Y at %I:%M %p") if signer.signed_at else "",
                    "ip_address": signer.ip_address or "",
                }

        # Check if this was a builder-generated lease by looking up LeaseBuilder
        from database.models import LeaseBuilder
        lease_data = None

        builder_result = await session.execute(
            select(LeaseBuilder).where(LeaseBuilder.lease_document_id == lease.id)
        )
        builder = builder_result.scalar_one_or_none()

        if builder and builder.lease_data:
            try:
                lease_data = json.loads(builder.lease_data)
                logger.info(f"[ESIGN] Found builder data for lease {lease.id}")
            except json.JSONDecodeError:
                logger.warning(f"[ESIGN] Builder lease_data is not valid JSON")

        # Fallback: check notes field for legacy builder data
        if not lease_data and lease.notes and lease.notes.startswith("{"):
            try:
                lease_data = json.loads(lease.notes)
            except json.JSONDecodeError:
                pass

        logger.info(f"[ESIGN] has_builder_data: {lease_data is not None}, "
                     f"has_prop: {lease.property_ref is not None}, "
                     f"file_url: {lease.file_url}")

        if lease_data and lease.property_ref:
            # Builder lease — re-render with signatures inline
            return _generate_signed_builder_pdf(lease, lease_data, signatures)
        else:
            # Uploaded PDF — append signature page
            logger.info(f"[ESIGN] Using pypdf append path for uploaded PDF")
            return _generate_signature_page_pdf(lease, envelope, signatures)

    finally:
        if own_session:
            await ctx.__aexit__(None, None, None)


def _generate_signed_builder_pdf(lease, lease_data: dict, signatures: dict) -> dict:
    """Re-render a builder lease HTML with embedded signatures."""
    from webapp.services.lease_pdf_service import generate_signed_lease_pdf

    prop = lease.property_ref
    property_info = {
        "address": prop.address if prop else "",
        "city": prop.city if prop else "",
        "state": prop.state if prop else "MI",
        "zip_code": prop.zip_code if prop else "",
        "entity_name": prop.entity if prop else "",
    }

    tenant_info = {}
    if lease.tenant_ref:
        tenant_info = {
            "name": lease.tenant_ref.name,
            "email": lease.tenant_ref.email or "",
        }

    landlord_info = lease_data.get("landlord", {})

    return generate_signed_lease_pdf(lease_data, property_info, tenant_info, landlord_info, signatures)


def _generate_signature_page_pdf(lease, envelope, signatures: dict) -> dict:
    """Generate a standalone signature page and append to the uploaded PDF."""
    try:
        from weasyprint import HTML
    except ImportError:
        return {"error": "weasyprint not installed"}

    # Build signature page HTML with cursive names (DocuSign-style)
    sig_rows = ""
    for key, sig in signatures.items():
        signed_date = sig['signed_at'].split(' at ')[0] if ' at ' in sig['signed_at'] else sig['signed_at']
        sig_rows += f"""
        <div style="margin-bottom: 30pt; page-break-inside: avoid;">
            <h3 style="font-size: 11pt; font-weight: bold; margin-bottom: 4pt;">
                {sig['role'].upper()}:
            </h3>
            <p style="font-family: 'Dancing Script', cursive; font-size: 28pt; color: #1a237e;
                      margin: 0; line-height: 1.2; border-bottom: 1px solid #333;
                      display: inline-block; padding-bottom: 2pt; min-width: 300pt;">
                {sig['name']}
            </p>
            <p style="font-size: 9pt; color: #666; margin-top: 2pt;">
                {sig['name']} ({sig.get('email', '')}) — Electronically signed on {sig['signed_at']}
                {(' — IP: ' + sig['ip_address']) if sig['ip_address'] else ''}
            </p>
            <p style="margin-top: 6pt;">Date: <span style="font-family: 'Dancing Script', cursive; font-size: 14pt; color: #1a237e;">{signed_date}</span></p>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Dancing+Script:wght@700&display=swap');
        @page {{ size: letter; margin: 1in; }}
        body {{ font-family: "Times New Roman", Times, serif; font-size: 11pt; line-height: 1.5; }}
        h2 {{ font-size: 13pt; border-bottom: 1px solid #999; padding-bottom: 3pt; }}
    </style>
</head>
<body>
    <h2>SIGNATURES</h2>
    <p>By signing below, the parties acknowledge that they have read and understood the terms of this
    agreement and agree to be bound by all of its provisions.</p>
    {sig_rows}
</body>
</html>"""

    # Render signature page to PDF
    sig_page_path = SIGNED_DIR / f"sigpage_{uuid.uuid4().hex[:8]}.pdf"
    try:
        HTML(string=html_content).write_pdf(str(sig_page_path))
    except Exception as e:
        logger.error(f"Signature page PDF generation failed: {e}")
        return {"error": f"Signature page generation failed: {e}"}

    # Append to original PDF
    original_path = str(Path(UPLOAD_BASE) / lease.file_url.removeprefix("/uploads/"))
    output_filename = f"signed_{uuid.uuid4().hex[:12]}.pdf"
    output_path = SIGNED_DIR / output_filename
    logger.info(f"[ESIGN] Original PDF path: {original_path}, exists: {Path(original_path).exists()}")
    logger.info(f"[ESIGN] Output path: {output_path}")

    try:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()

        # Add all pages from original
        reader = PdfReader(original_path)
        for page in reader.pages:
            writer.add_page(page)

        # Add signature page
        sig_reader = PdfReader(str(sig_page_path))
        for page in sig_reader.pages:
            writer.add_page(page)

        with open(output_path, "wb") as f:
            writer.write(f)

        # Clean up temp signature page
        sig_page_path.unlink(missing_ok=True)

    except ImportError:
        logger.error("pypdf not installed — cannot append signature page")
        return {"error": "pypdf not installed"}
    except Exception as e:
        logger.error(f"PDF merge failed: {e}")
        return {"error": f"PDF merge failed: {e}"}

    file_url = f"/uploads/leases/signed/{output_filename}"
    return {
        "file_url": file_url,
        "file_path": str(output_path),
        "file_size": output_path.stat().st_size,
    }


# =============================================================================
# Email Helpers
# =============================================================================

async def _send_signing_email(signer, envelope, lease, token: str):
    """Send the 'Please sign' email with unique signing link."""
    try:
        return await _send_signing_email_inner(signer, envelope, lease, token)
    except Exception as e:
        logger.error(f"[ESIGN] Exception sending signing email to {signer.email}: {e}", exc_info=True)


async def _send_signing_email_inner(signer, envelope, lease, token: str):
    from webapp.services.email_service import email_service

    signing_url = f"{web_config.site_url.rstrip('/')}/sign/{token}"

    property_address = ""
    if lease.property_ref:
        p = lease.property_ref
        property_address = f"{p.address}, {p.city}, {p.state} {p.zip_code}"

    subject = f"Please sign: {lease.title}"
    if property_address:
        subject += f" for {property_address}"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: #1e40af; padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 20px;">Blue Deer Property Management</h1>
        </div>
        <div style="padding: 30px; background: #f9fafb; border: 1px solid #e5e7eb;">
            <h2 style="color: #111827; margin-top: 0;">Signature Requested</h2>
            <p style="color: #374151;">Hi {signer.name},</p>
            <p style="color: #374151;">
                You have been asked to sign <strong>{lease.title}</strong>
                {(' for <strong>' + property_address + '</strong>') if property_address else ''}.
            </p>
            <p style="color: #374151;">Your role: <strong>{signer.role.title()}</strong></p>
            <div style="text-align: center; margin: 30px 0;">
                <a href="{signing_url}"
                   style="display: inline-block; background: #1e40af; color: white; padding: 14px 32px;
                          text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px;">
                    Review &amp; Sign Document
                </a>
            </div>
            <p style="color: #6b7280; font-size: 13px;">
                This link expires in 7 days. If you did not expect this request, please disregard this email.
            </p>
        </div>
        <div style="padding: 15px; text-align: center; color: #9ca3af; font-size: 12px;">
            Blue Deer Property Management
        </div>
    </div>
    """

    text_body = (
        f"Hi {signer.name},\n\n"
        f"You have been asked to sign {lease.title}"
        f"{(' for ' + property_address) if property_address else ''}.\n\n"
        f"Your role: {signer.role.title()}\n\n"
        f"Sign here: {signing_url}\n\n"
        f"This link expires in 7 days.\n\n"
        f"Blue Deer Property Management"
    )

    logger.info(f"[ESIGN] Sending signing email to {signer.email} (configured: {email_service.is_configured})")
    result = await email_service.send_email(
        to=signer.email,
        subject=subject,
        body=text_body,
        html_body=html_body,
    )
    if result.success:
        logger.info(f"[ESIGN] Signing email sent to {signer.email}: {result.message_id}")
    else:
        logger.error(f"[ESIGN] Failed to send signing email to {signer.email}: {result.error_message}")


async def _send_completion_emails(envelope_id: int, session=None):
    """Notify all parties when all signatures are complete."""
    from database.models import ESignEnvelope, ESignSigner, LeaseDocument
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from webapp.services.email_service import email_service

    result = await session.execute(
        select(ESignEnvelope)
        .where(ESignEnvelope.id == envelope_id)
        .options(selectinload(ESignEnvelope.signer_records))
    )
    envelope = result.scalar_one_or_none()
    if not envelope:
        return

    lease_result = await session.execute(
        select(LeaseDocument)
        .where(LeaseDocument.id == envelope.lease_document_id)
        .options(selectinload(LeaseDocument.property_ref))
    )
    lease = lease_result.scalar_one_or_none()
    lease_title = lease.title if lease else "Lease Document"

    for signer in envelope.signer_records:
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: #059669; padding: 20px; text-align: center;">
                <h1 style="color: white; margin: 0; font-size: 20px;">Document Fully Signed</h1>
            </div>
            <div style="padding: 30px; background: #f9fafb; border: 1px solid #e5e7eb;">
                <p style="color: #374151;">Hi {signer.name},</p>
                <p style="color: #374151;">
                    All parties have signed <strong>{lease_title}</strong>.
                    The fully executed document is now available.
                </p>
                <p style="color: #6b7280; font-size: 13px;">
                    If you need a copy of the signed document, please contact your property manager.
                </p>
            </div>
            <div style="padding: 15px; text-align: center; color: #9ca3af; font-size: 12px;">
                Blue Deer Property Management
            </div>
        </div>
        """

        await email_service.send_email(
            to=signer.email,
            subject=f"Completed: {lease_title} — All Signatures Received",
            body=f"Hi {signer.name},\n\nAll parties have signed {lease_title}.\n\nBlue Deer Property Management",
            html_body=html_body,
        )

    await _log_audit(session, envelope_id, "completion_emails_sent")


async def _send_decline_notification(signer, session=None):
    """Notify admin when a signer declines."""
    from webapp.services.email_service import email_service

    # Send to the configured from-email (admin)
    admin_email = web_config.email_from
    if not admin_email:
        return

    await email_service.send_email(
        to=admin_email,
        subject=f"E-Sign Declined: {signer.name} declined to sign",
        body=(
            f"{signer.name} ({signer.email}) has declined to sign.\n"
            f"Role: {signer.role}\n"
            f"Reason: {signer.decline_reason or 'No reason given'}\n"
        ),
    )
