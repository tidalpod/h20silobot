"""In-house e-signature service.

Replaces DocuSign with token-based email links, canvas signature capture,
and WeasyPrint PDF generation with embedded signatures.
"""

import base64
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from webapp.config import web_config
from webapp.services.storage_service import storage, UPLOAD_BASE

logger = logging.getLogger(__name__)

# Local dirs still needed for temp WeasyPrint operations
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
        try:
            if "," in signature_data_base64:
                signature_data_base64 = signature_data_base64.split(",", 1)[1]
            sig_bytes = base64.b64decode(signature_data_base64)
            key = f"leases/signatures/{sig_filename}"
            sig_url = storage.upload(key, sig_bytes, "image/png")
        except Exception as e:
            logger.error(f"Failed to save signature: {e}")
            return {"error": "Invalid signature data"}

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
                # image_path stores the URL/path for downstream use
                sig_ref = signer.signature_file_url
                logger.info(f"[ESIGN] Signer {signer.name} sig ref: {sig_ref}")
                signatures[f"{signer.role}_{signer.id}"] = {
                    "name": signer.name,
                    "email": signer.email,
                    "role": signer.role,
                    "image_path": sig_ref,
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
            pdf_result = _generate_signed_builder_pdf(lease, lease_data, signatures)
        else:
            # Uploaded PDF — append signature page
            logger.info(f"[ESIGN] Using pypdf append path for uploaded PDF")
            pdf_result = _generate_signature_page_pdf(lease, envelope, signatures)

        if "error" in pdf_result:
            return pdf_result

        # Load audit logs and append audit trail page
        from database.models import ESignAuditLog
        audit_result = await session.execute(
            select(ESignAuditLog)
            .where(ESignAuditLog.envelope_id == envelope_id)
            .options(selectinload(ESignAuditLog.signer))
            .order_by(ESignAuditLog.created_at)
        )
        audit_logs = audit_result.scalars().all()

        try:
            _append_audit_trail(pdf_result["file_path"], lease, envelope, audit_logs)
            logger.info(f"[ESIGN] Audit trail appended to {pdf_result['file_path']}")
        except Exception as e:
            logger.error(f"[ESIGN] Failed to append audit trail: {e}", exc_info=True)

        return pdf_result

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

    # Render signature page to temp PDF
    fd_sig, sig_page_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd_sig)
    try:
        HTML(string=html_content).write_pdf(sig_page_path)
    except Exception as e:
        logger.error(f"Signature page PDF generation failed: {e}")
        Path(sig_page_path).unlink(missing_ok=True)
        return {"error": f"Signature page generation failed: {e}"}

    # Download original PDF (may be in R2 or local)
    original_tmp = storage.download_to_temp(lease.file_url, suffix=".pdf")
    if not original_tmp:
        # Fallback: try direct local path
        local = Path(UPLOAD_BASE) / lease.file_url.removeprefix("/uploads/")
        if local.exists():
            original_tmp = str(local)
        else:
            Path(sig_page_path).unlink(missing_ok=True)
            return {"error": "Original PDF not found"}

    output_filename = f"signed_{uuid.uuid4().hex[:12]}.pdf"
    fd_out, output_tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd_out)
    logger.info(f"[ESIGN] Original PDF source: {lease.file_url}")

    try:
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()

        reader = PdfReader(original_tmp)
        for page in reader.pages:
            writer.add_page(page)

        sig_reader = PdfReader(sig_page_path)
        for page in sig_reader.pages:
            writer.add_page(page)

        with open(output_tmp_path, "wb") as f:
            writer.write(f)

    except ImportError:
        logger.error("pypdf not installed — cannot append signature page")
        return {"error": "pypdf not installed"}
    except Exception as e:
        logger.error(f"PDF merge failed: {e}")
        return {"error": f"PDF merge failed: {e}"}
    finally:
        Path(sig_page_path).unlink(missing_ok=True)
        # Clean up downloaded original if it was a temp file
        if original_tmp != str(Path(UPLOAD_BASE) / lease.file_url.removeprefix("/uploads/")):
            Path(original_tmp).unlink(missing_ok=True)

    # Upload merged PDF to storage
    key = f"leases/signed/{output_filename}"
    file_size = Path(output_tmp_path).stat().st_size
    file_url = storage.upload_from_path(key, output_tmp_path, "application/pdf")

    # Resolve local path for audit trail append
    local_path = storage.resolve_local_path(file_url)
    final_path = str(local_path) if local_path else output_tmp_path

    return {
        "file_url": file_url,
        "file_path": final_path,
        "file_size": file_size,
    }


# =============================================================================
# Audit Trail
# =============================================================================

# Map action codes to display info
_AUDIT_ICONS = {
    "envelope_created": ("CREATED", "#6b7280"),
    "email_sent": ("SENT", "#2563eb"),
    "email_resent": ("RESENT", "#2563eb"),
    "signer_queued": ("QUEUED", "#6b7280"),
    "link_opened": ("VIEWED", "#8b5cf6"),
    "signed": ("SIGNED", "#059669"),
    "declined": ("DECLINED", "#dc2626"),
    "voided": ("VOIDED", "#dc2626"),
    "pdf_generated": ("PDF", "#059669"),
    "completion_emails_sent": ("NOTIFIED", "#2563eb"),
}


def _build_audit_trail_html(lease, envelope, audit_logs) -> str:
    """Build the audit trail HTML page matching Dropbox Sign style."""
    property_address = ""
    if lease.property_ref:
        p = lease.property_ref
        property_address = f"{p.address}, {p.city}, {p.state} {p.zip_code}"

    # Document info
    doc_id = f"{envelope.id:08d}"
    status = envelope.status.value.title() if envelope.status else "Unknown"
    completed_at = envelope.completed_at.strftime("%m/%d/%Y %H:%M:%S UTC") if envelope.completed_at else "—"

    # Build event rows
    event_rows = ""
    for log in audit_logs:
        label, color = _AUDIT_ICONS.get(log.action, (log.action.upper(), "#6b7280"))
        ts = log.created_at.strftime("%m / %d / %Y") if log.created_at else ""
        time_str = log.created_at.strftime("%H:%M:%S UTC") if log.created_at else ""

        # Build description
        details = {}
        if log.details:
            try:
                details = json.loads(log.details)
            except (json.JSONDecodeError, TypeError):
                pass

        signer_name = log.signer.name if log.signer else ""
        signer_email = log.signer.email if log.signer else details.get("email", "")
        desc = _audit_description(log.action, signer_name, signer_email, details)
        ip_line = f"<br/>IP: {log.ip_address}" if log.ip_address else ""

        event_rows += f"""
        <tr>
            <td style="padding: 18pt 8pt; vertical-align: top; width: 70pt; text-align: center;">
                <span style="font-size: 8pt; font-weight: bold; color: {color};
                             letter-spacing: 1pt; text-transform: uppercase;">{label}</span>
            </td>
            <td style="padding: 18pt 8pt; vertical-align: top; width: 110pt;">
                <strong style="font-size: 10pt;">{ts}</strong><br/>
                <span style="font-size: 9pt; color: #666;">{time_str}</span>
            </td>
            <td style="padding: 18pt 8pt; vertical-align: top; font-size: 9.5pt; color: #333;">
                {desc}{ip_line}
            </td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        @page {{ size: letter; margin: 0.75in; }}
        body {{ font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #333; }}
        .header {{ display: flex; justify-content: space-between; align-items: center;
                   border-bottom: 2px solid #111; padding-bottom: 12pt; margin-bottom: 20pt; }}
        .brand {{ font-size: 16pt; font-weight: bold; color: #1e40af; }}
        .trail-title {{ font-size: 14pt; color: #666; }}
        .info-table {{ width: 100%; margin-bottom: 20pt; border-collapse: collapse; }}
        .info-table td {{ padding: 6pt 8pt; font-size: 9.5pt; border-bottom: 1px solid #eee; }}
        .info-table td:first-child {{ font-weight: bold; color: #333; width: 140pt; }}
        .info-table td:last-child {{ color: #555; }}
        .note {{ background: #f9fafb; border-top: 1px solid #ddd; border-bottom: 1px solid #ddd;
                 padding: 8pt 12pt; font-size: 9pt; font-weight: bold; margin-bottom: 20pt; }}
        .history-title {{ font-size: 16pt; color: #999; margin-bottom: 12pt; }}
        .events {{ width: 100%; border-collapse: collapse; }}
        .events tr {{ border-bottom: 1px solid #eee; }}
        .status-dot {{ display: inline-block; width: 8pt; height: 8pt; border-radius: 50%;
                       background: #059669; margin-right: 4pt; vertical-align: middle; }}
    </style>
</head>
<body>
    <table style="width: 100%; margin-bottom: 20pt;">
        <tr>
            <td><span class="brand">Blue Deer</span></td>
            <td style="text-align: right;"><span class="trail-title">Audit trail</span></td>
        </tr>
    </table>
    <hr style="border: none; border-top: 2px solid #111; margin-bottom: 20pt;">

    <table class="info-table">
        <tr><td>Title</td><td>{lease.title}</td></tr>
        <tr><td>Property</td><td>{property_address}</td></tr>
        <tr><td>Document ID</td><td>{doc_id}</td></tr>
        <tr><td>Status</td><td><span class="status-dot"></span> {status}</td></tr>
        <tr><td>Completed</td><td>{completed_at}</td></tr>
    </table>

    <div class="note">
        This document was requested on bluedeer.space and signed on bluedeer.space
    </div>

    <p class="history-title">Document History</p>

    <table class="events">
        {event_rows}
    </table>
</body>
</html>"""


def _audit_description(action: str, name: str, email: str, details: dict) -> str:
    """Generate a human-readable description for an audit event."""
    email_str = f" ({email})" if email else ""
    triggered_by = details.get("triggered_by", "")

    if action == "envelope_created":
        signers = details.get("signers", [])
        return f"Signing request created for {', '.join(signers)}"
    elif action == "email_sent":
        extra = f" (triggered by {triggered_by} signing)" if triggered_by else ""
        return f"Sent for signature to {name}{email_str}{extra}"
    elif action == "email_resent":
        return f"Signing email resent to {name}{email_str}"
    elif action == "signer_queued":
        order = details.get("order", 2)
        return f"{name}{email_str} queued as signer #{order} (sequential)"
    elif action == "link_opened":
        return f"Viewed by {name}{email_str}"
    elif action == "signed":
        sig_type = details.get("signature_type", "")
        return f"Signed by {name}{email_str}" + (f" ({sig_type})" if sig_type else "")
    elif action == "declined":
        reason = details.get("reason", "")
        return f"Declined by {name}{email_str}" + (f" — {reason}" if reason else "")
    elif action == "voided":
        reason = details.get("reason", "")
        return f"Voided" + (f" — {reason}" if reason else "")
    elif action == "pdf_generated":
        return "Signed PDF generated"
    elif action == "completion_emails_sent":
        return "Completion notifications sent to all parties"
    else:
        return f"{action}: {name}{email_str}"


def _append_audit_trail(signed_pdf_path: str, lease, envelope, audit_logs):
    """Generate audit trail PDF and append to the signed PDF.

    signed_pdf_path may be a local path.  After appending, if using R2 we
    re-upload the modified file.
    """
    try:
        from weasyprint import HTML
        from pypdf import PdfReader, PdfWriter
    except ImportError as e:
        logger.error(f"Missing dependency for audit trail: {e}")
        return

    html = _build_audit_trail_html(lease, envelope, audit_logs)

    # Render audit trail to temp PDF
    fd, trail_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    HTML(string=html).write_pdf(trail_path)

    # Append to signed PDF
    writer = PdfWriter()
    reader = PdfReader(signed_pdf_path)
    for page in reader.pages:
        writer.add_page(page)

    trail_reader = PdfReader(trail_path)
    for page in trail_reader.pages:
        writer.add_page(page)

    with open(signed_pdf_path, "wb") as f:
        writer.write(f)

    Path(trail_path).unlink(missing_ok=True)

    # If using R2, re-upload the modified file
    if storage.using_r2 and envelope.signed_file_url:
        key = storage._extract_key(envelope.signed_file_url)
        if key:
            storage.upload_from_path(key, signed_pdf_path, "application/pdf")


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
