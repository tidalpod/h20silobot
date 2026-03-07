"""DocuSign e-signature service — JWT Grant authentication + envelope management.

Usage:
  1. Set env vars (see .env.example for DOCUSIGN_* keys)
  2. Grant consent once in browser (URL in .env.example)
  3. Call send_for_signature() to create and send an envelope
  4. Call get_envelope_status() to check progress
  5. Call download_signed_document() when status is 'completed'
"""

import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from typing import Optional

import aiohttp
import jwt

from config import config

logger = logging.getLogger(__name__)

# Upload path for signed documents
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
SIGNED_DIR = Path(UPLOAD_BASE) / "leases" / "signed"
SIGNED_DIR.mkdir(parents=True, exist_ok=True)

# Token cache
_access_token = None
_token_expires_at = 0


def _get_private_key() -> Optional[str]:
    """Get DocuSign private key from env var content or file path."""
    if config.docusign_private_key:
        return config.docusign_private_key
    if config.docusign_private_key_path and Path(config.docusign_private_key_path).exists():
        return Path(config.docusign_private_key_path).read_text()
    return None


def is_configured() -> bool:
    """Check if DocuSign credentials are set."""
    return bool(
        config.docusign_integration_key
        and config.docusign_user_id
        and config.docusign_account_id
        and _get_private_key()
    )


async def _get_access_token() -> str:
    """Get a valid access token via JWT Grant, caching until expiry."""
    global _access_token, _token_expires_at

    if _access_token and time.time() < _token_expires_at - 60:
        return _access_token

    private_key = _get_private_key()
    if not private_key:
        raise RuntimeError("DocuSign private key not found. Set DOCUSIGN_PRIVATE_KEY or DOCUSIGN_PRIVATE_KEY_PATH.")

    now = int(time.time())
    payload = {
        "iss": config.docusign_integration_key,
        "sub": config.docusign_user_id,
        "aud": config.docusign_oauth_url.replace("https://", ""),
        "iat": now,
        "exp": now + 3600,
        "scope": "signature impersonation",
    }

    assertion = jwt.encode(payload, private_key, algorithm="RS256")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{config.docusign_oauth_url}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(f"DocuSign token request failed ({resp.status}): {body}")
                raise RuntimeError(f"DocuSign auth failed: {body}")
            data = await resp.json()

    _access_token = data["access_token"]
    _token_expires_at = now + data.get("expires_in", 3600)
    return _access_token


async def send_for_signature(
    pdf_path: str,
    document_name: str,
    signers: list[dict],
) -> dict:
    """Create and send a DocuSign envelope with the given PDF.

    Args:
        pdf_path: Absolute path to the PDF file.
        signers: List of dicts with keys: name, email, role ('tenant' or 'landlord').

    Returns:
        {"envelope_id": "...", "status": "sent"} on success,
        {"error": "..."} on failure.
    """
    if not is_configured():
        return {"error": "DocuSign is not configured. Set DOCUSIGN_* environment variables."}

    pdf = Path(pdf_path)
    if not pdf.exists():
        return {"error": f"PDF not found: {pdf_path}"}

    token = await _get_access_token()
    pdf_bytes = pdf.read_bytes()
    pdf_b64 = base64.b64encode(pdf_bytes).decode()

    # Build signer objects with signature tabs
    envelope_signers = []
    for i, signer in enumerate(signers, start=1):
        envelope_signers.append({
            "email": signer["email"],
            "name": signer["name"],
            "recipientId": str(i),
            "routingOrder": str(i),
            "tabs": {
                "signHereTabs": [
                    {
                        "anchorString": f"/sig{i}/",
                        "anchorUnits": "pixels",
                        "anchorXOffset": "0",
                        "anchorYOffset": "-10",
                    }
                ],
                "dateSignedTabs": [
                    {
                        "anchorString": f"/date{i}/",
                        "anchorUnits": "pixels",
                        "anchorXOffset": "0",
                        "anchorYOffset": "-10",
                    }
                ],
            },
        })

    envelope = {
        "emailSubject": f"Please sign: {document_name}",
        "emailBlurb": (
            f"Please review and sign the attached document: {document_name}. "
            "Click the link below to review and sign electronically."
        ),
        "documents": [
            {
                "documentBase64": pdf_b64,
                "name": document_name,
                "fileExtension": "pdf",
                "documentId": "1",
            }
        ],
        "recipients": {
            "signers": envelope_signers,
        },
        "status": "sent",
    }

    base_url = config.docusign_base_url
    account_id = config.docusign_account_id

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url}/v2.1/accounts/{account_id}/envelopes",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=envelope,
        ) as resp:
            body = await resp.json()
            if resp.status not in (200, 201):
                logger.error(f"DocuSign create envelope failed ({resp.status}): {body}")
                return {"error": body.get("message", f"DocuSign API error {resp.status}")}

    return {
        "envelope_id": body["envelopeId"],
        "status": body.get("status", "sent"),
    }


async def get_envelope_status(envelope_id: str) -> dict:
    """Get the current status of an envelope.

    Returns:
        {"status": "sent|delivered|completed|declined|voided", "signers": [...]}
    """
    token = await _get_access_token()
    base_url = config.docusign_base_url
    account_id = config.docusign_account_id

    async with aiohttp.ClientSession() as session:
        # Get envelope status
        async with session.get(
            f"{base_url}/v2.1/accounts/{account_id}/envelopes/{envelope_id}",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                return {"error": f"Failed to get envelope: {body}"}
            env_data = await resp.json()

        # Get recipients
        async with session.get(
            f"{base_url}/v2.1/accounts/{account_id}/envelopes/{envelope_id}/recipients",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            recipients = {}
            if resp.status == 200:
                recipients = await resp.json()

    signer_statuses = []
    for signer in recipients.get("signers", []):
        signer_statuses.append({
            "name": signer.get("name"),
            "email": signer.get("email"),
            "status": signer.get("status"),
            "signed_at": signer.get("signedDateTime"),
            "delivered_at": signer.get("deliveredDateTime"),
        })

    return {
        "status": env_data.get("status", "unknown"),
        "signers": signer_statuses,
        "sent_at": env_data.get("sentDateTime"),
        "completed_at": env_data.get("completedDateTime"),
    }


async def download_signed_document(envelope_id: str) -> dict:
    """Download the completed signed document.

    Returns:
        {"file_url": "/uploads/leases/signed/...", "file_path": "..."} on success,
        {"error": "..."} on failure.
    """
    token = await _get_access_token()
    base_url = config.docusign_base_url
    account_id = config.docusign_account_id

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url}/v2.1/accounts/{account_id}/envelopes/{envelope_id}/documents/combined",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                return {"error": f"Failed to download signed document (status {resp.status})"}
            pdf_bytes = await resp.read()

    filename = f"signed_{uuid.uuid4().hex[:12]}.pdf"
    filepath = SIGNED_DIR / filename
    filepath.write_bytes(pdf_bytes)

    return {
        "file_url": f"/uploads/leases/signed/{filename}",
        "file_path": str(filepath),
        "file_size": len(pdf_bytes),
    }


async def void_envelope(envelope_id: str, reason: str = "Voided by landlord") -> dict:
    """Void an in-progress envelope."""
    token = await _get_access_token()
    base_url = config.docusign_base_url
    account_id = config.docusign_account_id

    async with aiohttp.ClientSession() as session:
        async with session.put(
            f"{base_url}/v2.1/accounts/{account_id}/envelopes/{envelope_id}",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"status": "voided", "voidedReason": reason},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                return {"error": f"Failed to void envelope: {body}"}

    return {"status": "voided"}
