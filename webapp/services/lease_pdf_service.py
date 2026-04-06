"""Lease PDF generation via weasyprint.

Renders a full HTML template with all lease data + boilerplate,
then converts to multi-page PDF.  Structured to match TurboTenant
Michigan lease format with numbered sections and tables.
"""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from webapp.services.lease_templates import (
    SECTION_2_PROVISIONS,
    SECTION_3_GENERAL_PROVISIONS,
    COMPREHENSIVE_SECTION_2_PROVISIONS,
    COMPREHENSIVE_SECTION_3_PROVISIONS,
    SECTION_4_TENANT_RESPONSIBILITIES,
    MICHIGAN_TRUTH_IN_RENTING,
    MICHIGAN_SECURITY_DEPOSIT_LAW,
    MICHIGAN_LEAD_PAINT_DISCLOSURE,
    ordinal,
)
from webapp.services.storage_service import storage

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


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


def _build_section_2(data: dict, provision_templates: list = None) -> list:
    """Build Section 2 (Special Provisions) from lease data + templates.

    Returns a list of dicts with 'key', 'title', 'text' for each provision.
    Some provisions have variable data interpolated.
    """
    if provision_templates is None:
        provision_templates = SECTION_2_PROVISIONS

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

    for template in provision_templates:
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
        elif key == "nsf_fees":
            nsf_fee = data.get("nsf_fee", 20)
            nsf_display = _format_currency(nsf_fee) if isinstance(nsf_fee, (int, float)) else f"${nsf_fee}"
            try:
                text = text.format(nsf_fee=nsf_display)
            except (KeyError, IndexError):
                pass
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
        elif key == "alterations_repairs_by_tenant":
            max_amt = data.get("max_repair_amount", 100)
            text = text.format(max_repair_amount=_format_currency(max_amt))

        provisions.append({"key": key, "title": title, "text": text})

    return provisions


def _build_section_4(data: dict) -> list:
    """Build Section 4 (Tenant Responsibilities) for comprehensive lease."""
    provisions = []
    water_method = data.get("water_bill_method", "direct")
    water_method_text = (
        "directly to the Tenant" if water_method == "direct"
        else "reimbursed to the Landlord"
    )

    for template in SECTION_4_TENANT_RESPONSIBILITIES:
        key = template.get("key", "")
        title = template["title"]
        text = template["text"]

        if key == "water_bill_payment":
            text = text.format(water_bill_method=water_method_text)

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
        ("stove", "Stove"),
        ("fridge", "Refrigerator"),
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
    is_comprehensive = data.get("template_type") == "comprehensive"

    if is_comprehensive:
        section_2 = _build_section_2(data, COMPREHENSIVE_SECTION_2_PROVISIONS)
        section_3 = COMPREHENSIVE_SECTION_3_PROVISIONS
        section_4 = _build_section_4(data)
    else:
        section_2 = _build_section_2(data, SECTION_2_PROVISIONS)
        section_3 = SECTION_3_GENERAL_PROVISIONS
        section_4 = None

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
                # Try reading via storage (handles both local and R2)
                img_data = storage.download(sig["image_path"])
                if img_data is None:
                    # Fallback: try reading as a direct file path
                    sig_path = Path(sig["image_path"])
                    if sig_path.exists():
                        img_data = sig_path.read_bytes()
                if img_data:
                    b64 = base64.b64encode(img_data).decode()
                    sig_images[key] = {
                        **sig,
                        "image_data_uri": f"data:image/png;base64,{b64}",
                    }
                else:
                    logger.warning(f"Could not read signature image {sig.get('image_path')}")
                    sig_images[key] = sig
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
        section_3_provisions=section_3,
        section_4_provisions=section_4,
        is_comprehensive=is_comprehensive,
        michigan_truth_in_renting=MICHIGAN_TRUTH_IN_RENTING,
        michigan_security_deposit=MICHIGAN_SECURITY_DEPOSIT_LAW,
        michigan_lead_paint=MICHIGAN_LEAD_PAINT_DISCLOSURE if data.get("lead_paint_disclosure") else None,
        additional_terms=additional_terms,
        signatures=sig_images if sig_images else None,
        total_monthly_rent=total_monthly_rent,
        total_deposits=total_deposits,
        move_in_fee_total=move_in_fee_total,
        nonrefundable_fees=data.get("nonrefundable_fees", {}),
        furnishings_included=data.get("furnishings_included", ""),
        utilities_display=utilities_display,
        format_date=_format_date,
        format_currency=_format_currency,
        ordinal_suffix=_ordinal_suffix,
        generated_date=datetime.utcnow().strftime("%B %d, %Y"),
    )
    return html


def generate_lease_pdf(data: dict, property_info: dict, tenant_info: dict, landlord_info: dict) -> dict:
    """Generate lease PDF and upload to storage. Returns file info."""
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint not installed — cannot generate PDF")
        return {"error": "PDF generation not available (weasyprint not installed)"}

    html = generate_lease_html(data, property_info, tenant_info, landlord_info)

    filename = f"lease_{uuid.uuid4().hex[:12]}.pdf"
    key = f"leases/{filename}"

    # Write to temp file first (WeasyPrint needs a path)
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        HTML(string=html).write_pdf(tmp_path)
        file_size = Path(tmp_path).stat().st_size
        file_url = storage.upload_from_path(key, tmp_path, "application/pdf")
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return {"error": f"PDF generation failed: {str(e)}"}
    finally:
        # Clean up temp file if storage copied it (not if it IS the local file)
        if storage.using_r2:
            Path(tmp_path).unlink(missing_ok=True)

    # For local storage, resolve the actual path
    local_path = storage.resolve_local_path(file_url)

    return {
        "file_url": file_url,
        "file_path": str(local_path) if local_path else tmp_path,
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

    filename = f"signed_{uuid.uuid4().hex[:12]}.pdf"
    key = f"leases/signed/{filename}"

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)

    try:
        HTML(string=html).write_pdf(tmp_path)
        file_size = Path(tmp_path).stat().st_size
        # Don't upload to R2 yet — caller may append audit trail first
    except Exception as e:
        logger.error(f"Signed PDF generation failed: {e}")
        Path(tmp_path).unlink(missing_ok=True)
        return {"error": f"Signed PDF generation failed: {str(e)}"}

    return {
        "file_url": None,  # Will be set after audit trail is appended
        "file_path": tmp_path,
        "file_name": filename,
        "file_size": file_size,
        "storage_key": key,
    }
