"""Lease PDF generation via weasyprint.

Renders a full HTML template with all lease data + boilerplate,
then converts to multi-page PDF.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from webapp.services.lease_templates import (
    SECTION_2_TEMPLATES,
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
        return d.strftime("%B %d, %Y")
    except (ValueError, TypeError):
        return str(date_str)


def _format_currency(amount) -> str:
    """Format amount as currency."""
    if amount is None:
        return "$0.00"
    return f"${float(amount):,.2f}"


def _build_section_2(data: dict) -> list:
    """Build Section 2 (Special Provisions) from lease data."""
    provisions = []

    # 1. Lease Term
    lease_type = data.get("lease_type", "fixed")
    if lease_type == "fixed":
        exp_action = data.get("expiration_action", "continue_mtm")
        exp_text = SECTION_2_TEMPLATES.get(f"expiration_{exp_action}", "")
        provisions.append(
            SECTION_2_TEMPLATES["lease_term_fixed"].format(
                start_date=_format_date(data.get("start_date")),
                end_date=_format_date(data.get("end_date")),
                expiration_action=exp_text,
            )
        )
    else:
        provisions.append(
            SECTION_2_TEMPLATES["lease_term_mtm"].format(
                start_date=_format_date(data.get("start_date")),
            )
        )

    # 2. Rent
    due_day = data.get("rent_due_day", 1)
    methods = data.get("payment_methods", [])
    method_labels = {
        "ach": "ACH Bank Transfer",
        "check": "Personal Check",
        "money_order": "Money Order",
        "bluedeer": "Blue Deer Tenant Portal",
        "cash": "Cash",
    }
    method_str = ", ".join(method_labels.get(m, m) for m in methods) if methods else "as agreed"
    provisions.append(
        SECTION_2_TEMPLATES["rent_payment"].format(
            monthly_rent=_format_currency(data.get("monthly_rent", 0)).lstrip("$"),
            rent_due_day=due_day,
            ordinal=ordinal(due_day),
            payment_methods=method_str,
        )
    )

    # 3. Late Fee
    provisions.append(
        SECTION_2_TEMPLATES["late_fee"].format(
            grace_days=data.get("late_fee_grace_days", 5),
            ordinal_grace=ordinal(data.get("late_fee_grace_days", 5)),
            late_fee_daily=_format_currency(data.get("late_fee_daily", 15)).lstrip("$"),
            late_fee_max_days=data.get("late_fee_max_days", 5),
            late_fee_max=_format_currency(
                float(data.get("late_fee_daily", 15)) * int(data.get("late_fee_max_days", 5))
            ).lstrip("$"),
        )
    )

    # 4. Security Deposit
    if data.get("security_deposit"):
        provisions.append(
            SECTION_2_TEMPLATES["security_deposit"].format(
                security_deposit=_format_currency(data.get("security_deposit")).lstrip("$"),
                deposit_bank_name=data.get("deposit_bank_name", "___________"),
                deposit_bank_address=data.get("deposit_bank_address", "___________"),
            )
        )

    # 5. Prorated Rent
    if data.get("prorated_rent"):
        provisions.append(
            SECTION_2_TEMPLATES["prorated_rent"].format(
                prorated_rent=_format_currency(data.get("prorated_rent")).lstrip("$"),
                prorated_month=_format_date(data.get("start_date")),
            )
        )

    # 6. Move-in Fees
    fees = data.get("move_in_fees", [])
    if fees:
        rows = "\n".join(f"  - {f.get('description', '')}: {_format_currency(f.get('amount', 0))}" for f in fees)
        provisions.append(
            SECTION_2_TEMPLATES["move_in_fees"].format(fees_table=rows)
        )

    # 7. Pets
    if data.get("pets_allowed"):
        pets = data.get("pets", [])
        pet_list = ", ".join(
            f"{p.get('type', '')} ({p.get('breed', 'Unknown')}, {p.get('weight', '?')} lbs)"
            for p in pets
        ) if pets else "As approved by Landlord"
        provisions.append(
            SECTION_2_TEMPLATES["pet_policy_allowed"].format(
                pet_deposit=_format_currency(data.get("pet_deposit", 0)).lstrip("$"),
                pet_rent=_format_currency(data.get("pet_rent", 0)).lstrip("$"),
                pet_list=pet_list,
            )
        )
    else:
        provisions.append(SECTION_2_TEMPLATES["pet_policy_not_allowed"])

    # 8. Smoking
    smoking = data.get("smoking_policy", "not_permitted")
    if smoking == "not_permitted":
        provisions.append(SECTION_2_TEMPLATES["smoking_not_permitted"])
    else:
        provisions.append(SECTION_2_TEMPLATES["smoking_designated_areas"])

    # 9. Parking
    if data.get("parking_rules"):
        provisions.append(
            SECTION_2_TEMPLATES["parking"].format(parking_rules=data["parking_rules"])
        )

    # 10. Renters Insurance
    if data.get("renters_insurance_required"):
        provisions.append(SECTION_2_TEMPLATES["renters_insurance"])

    # 11. Utilities
    utilities = data.get("utilities", {})
    if utilities:
        rows = "\n".join(
            f"  - {name.replace('_', ' ').title()}: {resp.title()}"
            for name, resp in utilities.items()
        )
        provisions.append(
            SECTION_2_TEMPLATES["utilities"].format(utility_table=rows)
        )

    # 12. Maintenance
    methods = data.get("maintenance_communication", [])
    if methods:
        method_labels = {
            "bluedeer_portal": "Blue Deer Tenant Portal",
            "email": "Email",
            "text": "Text Message",
            "phone": "Phone Call",
        }
        method_str = ", ".join(method_labels.get(m, m) for m in methods)
        provisions.append(
            SECTION_2_TEMPLATES["maintenance"].format(maintenance_methods=method_str)
        )

    # 13. Keys
    keys = data.get("keys", [])
    if keys:
        rows = "\n".join(f"  - {k.get('type', '')}: {k.get('count', 1)} key(s)" for k in keys)
        provisions.append(
            SECTION_2_TEMPLATES["keys"].format(keys_table=rows)
        )

    # 14. Early Termination
    if data.get("early_termination"):
        provisions.append(SECTION_2_TEMPLATES["early_termination"])

    return provisions


def generate_lease_html(data: dict, property_info: dict, tenant_info: dict, landlord_info: dict) -> str:
    """Generate the full lease HTML from data + boilerplate."""
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
        format_date=_format_date,
        format_currency=_format_currency,
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
