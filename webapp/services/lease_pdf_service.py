"""Lease PDF generation via weasyprint.

Renders a full HTML template with all lease data + boilerplate,
then converts to multi-page PDF.  Structured to match TurboTenant
Michigan lease format with numbered sections and tables.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from webapp.services.lease_templates import (
    SECTION_2_PROVISIONS,
    SECTION_3_GENERAL_PROVISIONS,
    MICHIGAN_TRUTH_IN_RENTING,
    MICHIGAN_SECURITY_DEPOSIT_LAW,
    MICHIGAN_LEAD_PAINT_DISCLOSURE,
    ordinal,
)

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
UPLOAD_BASE = os.environ.get("UPLOAD_PATH") or (
    "/app/uploads" if Path("/app/uploads").exists()
    else str(Path(__file__).resolve().parent.parent / "static" / "uploads")
)
LEASE_PDF_DIR = Path(UPLOAD_BASE) / "leases"
LEASE_PDF_DIR.mkdir(parents=True, exist_ok=True)


def _format_date(date_str: str) -> str:
    """Format a date string (YYYY-MM-DD) for display."""
    if not date_str:
        return "___________"
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.strftime("%m/%d/%Y")
    except (ValueError, TypeError):
        return str(date_str)


def _format_currency(amount) -> str:
    """Format amount as currency."""
    if amount is None:
        return "$0.00"
    return f"${float(amount):,.2f}"


def _ordinal_suffix(n) -> str:
    """Return ordinal suffix for a number."""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return ""
    return ordinal(n)


def _build_section_2(data: dict) -> list:
    """Build Section 2 (Special Provisions) from lease data + templates.

    Returns a list of dicts with 'key', 'title', 'text' for each provision.
    Some provisions have variable data interpolated.
    """
    provisions = []

    due_day = data.get("rent_due_day", 1)
    maintenance_methods = data.get("maintenance_communication", [])
    method_labels = {
        "bluedeer_portal": "Online Maintenance Requests via Blue Deer",
        "email": "Email",
        "text": "Text Message",
        "phone": "Phone Call",
        "us_mail": "US Mail",
        "other": "Other",
    }
    method_str = ", ".join(method_labels.get(m, m) for m in maintenance_methods) if maintenance_methods else "As agreed"

    for template in SECTION_2_PROVISIONS:
        key = template.get("key", "")
        title = template["title"]
        text = template["text"]

        # Interpolate variables for provisions that need them
        if key == "late_rent":
            text = text.format(
                rent_due_day=due_day,
                ordinal=ordinal(due_day),
                late_fee_daily=_format_currency(data.get("late_fee_daily", 15)).lstrip("$"),
                late_fee_grace_days=data.get("late_fee_grace_days", 5),
                late_fee_max_days=data.get("late_fee_max_days", 5),
            )
        elif key == "security_deposit_provisions":
            bank_name = data.get("deposit_bank_name", "___________")
            bank_addr = data.get("deposit_bank_address", "___________")
            # Split text for the template to render the bank table separately
            text_before_bank = (
                "Upon the due execution of this Agreement, Tenant shall deposit with Landlord a security "
                "deposit referenced in Section 1.8. The security deposit shall be held in a FDIC insured "
                "institution as shown below. The security deposit shall not exceed a sum equal to one and "
                "a half (1.5) times the monthly rent. Such deposit shall be returned to Tenant, and less "
                "any set-off for unpaid rent, unpaid late fees, unpaid utilities, damages, or any other "
                "money owing Landlord, along with an itemized statement showing any lawful charges or "
                "deductions, within thirty (30) days of lease termination, in accordance with the terms "
                "of this section and applicable laws."
            )
            provisions.append({
                "key": key,
                "title": title,
                "text": text.format(
                    deposit_bank_name=bank_name,
                    deposit_bank_address=bank_addr,
                ),
                "text_before_bank": text_before_bank,
            })
            continue
        elif key == "maintenance_communication":
            text = text.format(maintenance_methods=method_str)

        provisions.append({"key": key, "title": title, "text": text})

    return provisions


def _build_utilities_display(data: dict) -> dict:
    """Build a display-friendly utility responsibility dict."""
    utilities = data.get("utilities", {})

    # Full list of utility types matching TurboTenant format
    all_utilities = [
        ("electricity", "Electricity"),
        ("gas", "Gas"),
        ("sewer", "Sewer / Septic"),
        ("trash", "Trash"),
        ("water", "Water"),
        ("cable", "Cable / Satellite"),
        ("hoa", "HOA / Condo Fee"),
        ("internet", "Internet"),
        ("landscaping", "Landscaping"),
        ("phone", "Phone"),
        ("snow_removal", "Snow Removal"),
    ]

    display = {}
    for key, label in all_utilities:
        resp = utilities.get(key, "tenant")
        display[label] = resp.title() if resp else "Tenant"

    return display


def generate_lease_html(data: dict, property_info: dict, tenant_info: dict,
                        landlord_info: dict, signatures: dict = None) -> str:
    """Generate the full lease HTML from data + boilerplate.

    signatures: optional dict of signature data for e-signed leases.
        Keys are like "tenant_5", "landlord_3", values have:
        {"name", "role", "image_path", "signed_at", "ip_address"}
    """
    import base64
    section_2 = _build_section_2(data)

    # Build tenant list
    tenants = data.get("tenants", [])
    if not tenants and tenant_info:
        tenants = [tenant_info]

    additional_occupants = data.get("additional_occupants", [])
    cosigners = data.get("cosigners", [])

    # Property address
    address = property_info.get("address", "")
    city = property_info.get("city", "")
    state = property_info.get("state", "MI")
    zip_code = property_info.get("zip_code", "")
    full_address = f"{address}, {city}, {state} {zip_code}"

    additional_terms = data.get("additional_terms", "")

    # Calculate totals for summary table
    monthly_rent = float(data.get("monthly_rent", 0) or 0)
    pet_rent = float(data.get("pet_rent", 0) or 0) if data.get("pets_allowed") else 0
    total_monthly_rent = monthly_rent + pet_rent

    security_deposit = float(data.get("security_deposit", 0) or 0)
    pet_deposit = float(data.get("pet_deposit", 0) or 0) if data.get("pets_allowed") else 0
    other_deposit = float(data.get("other_deposit", 0) or 0)
    total_deposits = security_deposit + pet_deposit + other_deposit

    move_in_fees = data.get("move_in_fees", [])
    move_in_fee_total = sum(float(f.get("amount", 0)) for f in move_in_fees) if move_in_fees else 0

    # Build utilities display
    utilities_display = _build_utilities_display(data)

    # Convert signature image files to base64 data URIs for PDF embedding
    sig_images = {}
    if signatures:
        for key, sig in signatures.items():
            try:
                with open(sig["image_path"], "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                sig_images[key] = {
                    **sig,
                    "image_data_uri": f"data:image/png;base64,{b64}",
                }
            except Exception as e:
                logger.warning(f"Could not read signature image {sig.get('image_path')}: {e}")
                sig_images[key] = sig

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("leases/lease_pdf_template.html")

    html = template.render(
        property_address=full_address,
        property_info=property_info,
        tenants=tenants,
        additional_occupants=additional_occupants,
        cosigners=cosigners,
        landlord=landlord_info,
        lease_data=data,
        section_2_provisions=section_2,
        section_3_provisions=SECTION_3_GENERAL_PROVISIONS,
        michigan_truth_in_renting=MICHIGAN_TRUTH_IN_RENTING,
        michigan_security_deposit=MICHIGAN_SECURITY_DEPOSIT_LAW,
        michigan_lead_paint=MICHIGAN_LEAD_PAINT_DISCLOSURE if data.get("lead_paint_disclosure") else None,
        additional_terms=additional_terms,
        signatures=sig_images if sig_images else None,
        total_monthly_rent=total_monthly_rent,
        total_deposits=total_deposits,
        move_in_fee_total=move_in_fee_total,
        utilities_display=utilities_display,
        format_date=_format_date,
        format_currency=_format_currency,
        ordinal_suffix=_ordinal_suffix,
        generated_date=datetime.utcnow().strftime("%B %d, %Y"),
    )
    return html


def generate_lease_pdf(data: dict, property_info: dict, tenant_info: dict, landlord_info: dict) -> dict:
    """Generate lease PDF and save to disk. Returns file info."""
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint not installed — cannot generate PDF")
        return {"error": "PDF generation not available (weasyprint not installed)"}

    html = generate_lease_html(data, property_info, tenant_info, landlord_info)

    filename = f"lease_{uuid.uuid4().hex[:12]}.pdf"
    filepath = LEASE_PDF_DIR / filename

    try:
        HTML(string=html).write_pdf(str(filepath))
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return {"error": f"PDF generation failed: {str(e)}"}

    file_size = filepath.stat().st_size
    file_url = f"/uploads/leases/{filename}"

    return {
        "file_url": file_url,
        "file_path": str(filepath),
        "file_name": filename,
        "file_size": file_size,
    }


def generate_signed_lease_pdf(data: dict, property_info: dict, tenant_info: dict,
                              landlord_info: dict, signatures: dict) -> dict:
    """Generate a signed lease PDF with embedded signature images. Returns file info."""
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint not installed — cannot generate signed PDF")
        return {"error": "PDF generation not available (weasyprint not installed)"}

    html = generate_lease_html(data, property_info, tenant_info, landlord_info, signatures=signatures)

    signed_dir = LEASE_PDF_DIR / "signed"
    signed_dir.mkdir(parents=True, exist_ok=True)

    filename = f"signed_{uuid.uuid4().hex[:12]}.pdf"
    filepath = signed_dir / filename

    try:
        HTML(string=html).write_pdf(str(filepath))
    except Exception as e:
        logger.error(f"Signed PDF generation failed: {e}")
        return {"error": f"Signed PDF generation failed: {str(e)}"}

    file_size = filepath.stat().st_size
    file_url = f"/uploads/leases/signed/{filename}"

    return {
        "file_url": file_url,
        "file_path": str(filepath),
        "file_name": filename,
        "file_size": file_size,
    }
