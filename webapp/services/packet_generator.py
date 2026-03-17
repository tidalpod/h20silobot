"""MSHDA Landlord Packet PDF generator.

Overlays text onto a scanned (image-based) blank MSHDA packet PDF.
Uses ReportLab to create transparent text overlays and pypdf to merge
them onto the original scanned pages, then appends entity-specific
W-9 and Payee Authorization PDFs.

The blank packet template should be placed at:
    webapp/static/templates/mshda_blank_packet.pdf
"""

import io
import json
import logging
import os
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# Path to the blank MSHDA packet (20-page scanned PDF)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BLANK_PACKET_PATH = STATIC_DIR / "templates" / "mshda_blank_packet.pdf"
FONTS_DIR = STATIC_DIR / "fonts"

# Letter page dimensions in points (8.5 x 11 inches)
PAGE_W, PAGE_H = letter  # 612 x 792

# Register cursive font for signatures
CURSIVE_FONT = "Helvetica-BoldOblique"  # fallback
try:
    _cursive_path = FONTS_DIR / "GreatVibes-Regular.ttf"
    if _cursive_path.exists():
        pdfmetrics.registerFont(TTFont("GreatVibes", str(_cursive_path)))
        CURSIVE_FONT = "GreatVibes"
        logger.info("Registered GreatVibes cursive font for signatures")
except Exception as e:
    logger.warning(f"Failed to register cursive font, using fallback: {e}")

# =============================================================================
# Field coordinate map
# =============================================================================
# Each entry: page_number (0-indexed) -> list of (field_name, x, y, font_size)
# Fields ending with "__sig" render in cursive and look up the base field name.
# Coordinates are in points from bottom-left (ReportLab convention).
# =============================================================================

FIELD_MAP = {
    # ------------------------------------------------------------------
    # P2 (page 1): Communications notice
    # ------------------------------------------------------------------
    1: [
        ("tenant_name",    205, 342, 12),
        ("tenant_email",   205, 302, 12),
        ("owner_name",     205, 224, 12),
        ("owner_email",    215, 187, 12),
    ],

    # ------------------------------------------------------------------
    # P4 (page 3): Property Owner Checklist p1
    # Grid-calibrated at 300 DPI
    # ------------------------------------------------------------------
    3: [
        ("tenant_name",         120, 680, 11),
        ("unit_address",        105, 660, 10),
        ("city",                 50, 640, 11),
        ("state",               425, 640, 11),
        ("zip_code",            482, 640, 11),
        ("bedrooms",            155, 620, 11),
        ("bathrooms",           355, 620, 11),
        ("year_built",          310, 600, 11),
        ("proposed_rent",       510, 600, 11),
        # Property Owner section
        ("entity_name",        155, 212, 10),
        ("ein",                475, 212, 10),   # Business SSN/FEIN
        ("owner_name",         120, 195, 11),
        ("owner_phone",        100, 178, 10),
        ("owner_email",        395, 178, 10),
    ],

    # ------------------------------------------------------------------
    # P5 (page 4): Property Owner Checklist p2 — owner certification
    # Values go in blank space ABOVE each label row
    # ------------------------------------------------------------------
    4: [
        ("owner_name",          100, 330, 11),   # Above "Printed Name" label
        ("owner_title",         100, 308, 11),   # Above "Title" label
        ("owner_name__sig",     100, 285, 14),   # Above "Signature:" label
        ("signature_date",      420, 285, 11),   # Date field on Signature row
    ],

    # ------------------------------------------------------------------
    # P6 (page 5): HUD-52517 p2 — certifications, signatures at bottom
    # Values go in blank space ABOVE each label row
    # Grid-calibrated: labels at y≈250, 218, 192, 150
    # ------------------------------------------------------------------
    5: [
        ("owner_name",             60, 260, 10),   # Above "Print or Type Name" label
        ("tenant_name",           345, 260, 10),   # Right side Print Name
        ("owner_name__sig",        60, 232, 12),   # Above "Signature" label
        ("owner_mailing_address",  60, 205, 9),    # Above "Business Address" label
        ("owner_phone",            60, 168, 10),   # Above "Telephone Number" label
        ("signature_date",        260, 168, 10),   # Above "Date" label (left)
        ("tenant_sign_date",      490, 168, 10),   # Above "Date" label (right)
    ],

    # ------------------------------------------------------------------
    # P7 (page 6): HUD-52517 p1 — Request for Tenancy Approval
    # ------------------------------------------------------------------
    6: [
        ("unit_address",        325, 420, 10),
        ("lease_start_date",     60, 368, 10),
        ("bedrooms",            200, 368, 10),
        ("year_built",          265, 368, 10),
        ("proposed_rent",       350, 368, 10),
        ("utility_allowance",   430, 368, 10),
    ],

    # ------------------------------------------------------------------
    # P8 (page 7): Lead-Based Paint Disclosure
    # Grid-calibrated: initials at (a)y≈618, (b)y≈520, (e)y≈378
    # Signature at y≈238, Certification text y≈288
    # ------------------------------------------------------------------
    7: [
        ("property_address",     100, 712, 10),
        # Owner/Landlord initials on disclosure lines
        ("owner_initials",        55, 618, 10),   # (a) initial
        ("owner_initials",        55, 520, 10),   # (b) initial
        ("owner_initials",        55, 378, 10),   # (e) initial
        # Certification of Accuracy — signature section
        ("owner_name__sig",      120, 238, 12),   # Owner/Landlord Signature
        ("signature_date",       460, 238, 10),   # Date
    ],

    # ------------------------------------------------------------------
    # P9 (page 8): Owner Certification — Lead Paint
    # Grid-calibrated: Sig y≈268, Printed Name y≈248, Date y≈248
    # ------------------------------------------------------------------
    8: [
        ("property_address",     300, 700, 10),   # Full address (top)
        ("owner_name__sig",      120, 268, 12),   # Owner's Signature (cursive)
        ("owner_name",           120, 248, 10),   # Printed Name
        ("signature_date",       370, 248, 10),   # Date
    ],

    # ------------------------------------------------------------------
    # P11 (page 10): HCV Rules p2 — signatures at very bottom
    # ------------------------------------------------------------------
    10: [
        ("tenant_name",          160,  92, 10),
        ("tenant_sign_date",     490,  77, 10),
        ("owner_name__sig",      160,  57, 11),   # Signature (cursive)
        ("signature_date",       490,  42, 10),
    ],

    # ------------------------------------------------------------------
    # P13 (page 12): MSHDA Payee Authorization p1
    # ------------------------------------------------------------------
    12: [
        ("tenant_name",            410, 748, 10),
        ("entity_name",             55, 628, 10),
        ("owner_mailing_address",   55, 452, 10),
        ("owner_phone",            100, 372, 10),
        ("owner_email",            100, 357, 10),
    ],

    # ------------------------------------------------------------------
    # P14 (page 13): Payee Authorization p2 — bank info
    # ------------------------------------------------------------------
    13: [
        ("bank_name",              200, 728, 11),
        ("bank_routing_number",    200, 672, 11),
        ("bank_account_number",    200, 655, 11),
        ("owner_name__sig",        255, 422, 12),   # Signature (cursive)
        ("signature_date",         490, 405, 11),
    ],
}

# =============================================================================
# Checkbox coordinate map
# =============================================================================
# Each entry: page_number -> list of (field_name, x, y, size)
# An "X" is drawn if form_data[field_name] is truthy.
# =============================================================================

CHECKBOX_MAP = {
    # ------------------------------------------------------------------
    # P4 (page 3): Property Owner Checklist p1
    # All coordinates recalibrated from 300 DPI grid overlay
    # ------------------------------------------------------------------
    3: [
        # Transaction type (top of page)
        ("initial_occupancy",        28, 722, 9),
        # Barrier-Free Unit — Yes checkbox
        ("barrier_free_yes",        120, 557, 8),
        # Building Type (check one based on property_type)
        ("btype_highrise",           24, 508, 8),
        ("btype_lowrise",            24, 492, 8),
        ("btype_townhouse",          24, 476, 8),
        ("btype_duplex",             24, 460, 8),
        ("btype_triplex",            24, 444, 8),
        ("btype_fourplex",           24, 428, 8),
        ("btype_single_family",      24, 412, 8),
        ("btype_manufactured",       24, 396, 8),
        # Features Available — Water
        ("feat_water_city",          98, 358, 7),
        ("feat_water_well",         168, 358, 7),
        # Sewer
        ("feat_sewer_public",        82, 345, 7),
        ("feat_sewer_septic",       165, 345, 7),
        # Cooling System
        ("feat_cool_central",       105, 332, 7),
        ("feat_cool_window",        160, 332, 7),
        ("feat_cool_none",          218, 332, 7),
        # Heating System
        ("feat_heat_baseboard",     105, 320, 7),
        ("feat_heat_boiler",        165, 320, 7),
        ("feat_heat_central",       210, 320, 7),
        ("feat_heat_furnace",       262, 320, 7),
        # Indoor
        ("feat_indoor_cable",        62, 307, 7),
        ("feat_indoor_ceiling_fan", 128, 307, 7),
        ("feat_indoor_dryer",       178, 307, 7),
        ("feat_indoor_washer",      218, 307, 7),
        ("feat_indoor_hookups",     268, 307, 7),
        ("feat_indoor_laundry",     382, 307, 7),
        # Kitchen
        ("feat_kitchen_dishwasher",  82, 295, 7),
        ("feat_kitchen_disposal",   150, 295, 7),
        ("feat_kitchen_microwave",  243, 295, 7),
        ("feat_kitchen_fridge",     310, 295, 7),
        ("feat_kitchen_range",      388, 295, 7),
        # Outdoor
        ("feat_outdoor_balcony",     82, 282, 7),
        ("feat_outdoor_pool",       138, 282, 7),
        ("feat_outdoor_gated",      186, 282, 7),
        # Parking
        ("feat_parking_garage",      78, 270, 7),
        ("feat_parking_1car",       115, 270, 7),
        ("feat_parking_2car",       152, 270, 7),
        ("feat_parking_3car",       192, 270, 7),
        # Maintenance
        ("feat_maint_lawn",          82, 257, 7),
        ("feat_maint_pest",         125, 257, 7),
        ("feat_maint_trash",        192, 257, 7),
    ],

    # ------------------------------------------------------------------
    # P6 (page 5): HUD-52517 p2 — "c. Check one of the following:"
    # 3rd checkbox is on the RIGHT side of page at x≈477
    # ------------------------------------------------------------------
    5: [
        ("lead_completed_statement", 477, 598, 8),
    ],

    # P9 (page 8): Owner Certification — Lead Paint
    # 3rd checkbox: "Because the described property was constructed prior to Jan 1, 1978..."
    8: [
        ("lead_pre1978_ongoing",     48, 482, 10),
    ],
}


def _create_text_overlay(page_num: int, form_data: dict) -> Optional[bytes]:
    """Create a single-page transparent PDF with text at mapped coordinates.

    Returns PDF bytes for one page, or None if no fields for this page.
    """
    text_fields = FIELD_MAP.get(page_num, [])
    checkbox_fields = CHECKBOX_MAP.get(page_num, [])

    if not text_fields and not checkbox_fields:
        return None

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)

    # Draw text fields
    for field_name, x, y, font_size in text_fields:
        # Fields ending with "__sig" use cursive font and look up the base field
        if field_name.endswith("__sig"):
            actual_field = field_name[:-5]  # strip "__sig"
            value = form_data.get(actual_field, "")
            if value:
                c.setFont(CURSIVE_FONT, font_size)
                c.drawString(x, y, str(value))
        else:
            value = form_data.get(field_name, "")
            if value:
                c.setFont("Helvetica-Bold", font_size)
                c.drawString(x, y, str(value))

    # Draw checkbox fields
    for field_name, x, y, size in checkbox_fields:
        value = form_data.get(field_name)
        if value and str(value).lower() in ("true", "1", "yes", "on"):
            c.setFont("Helvetica-Bold", size)
            c.drawString(x, y, "X")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def generate_packet(
    form_data: dict,
    entity_w9_path: Optional[str] = None,
    entity_payee_path: Optional[str] = None,
    blank_pdf_path: Optional[str] = None,
) -> bytes:
    """Generate a filled MSHDA landlord packet PDF.

    Args:
        form_data: Dict of field values to overlay on the scanned pages.
        entity_w9_path: Path or URL to the entity's W-9 PDF.
        entity_payee_path: Path or URL to the entity's Payee Authorization PDF.
        blank_pdf_path: Override path to the blank packet PDF (for testing).

    Returns:
        bytes: The generated PDF file contents.
    """
    template_path = blank_pdf_path or str(BLANK_PACKET_PATH)

    if not os.path.exists(template_path):
        raise FileNotFoundError(
            f"Blank MSHDA packet not found at {template_path}. "
            "Place the scanned PDF at webapp/static/templates/mshda_blank_packet.pdf"
        )

    # Derive composite fields if not explicitly provided
    _derive_fields(form_data)

    reader = PdfReader(template_path)
    writer = PdfWriter()

    total_pages = len(reader.pages)
    logger.info(f"Processing {total_pages}-page blank packet")
    logger.info(f"Entity W-9 path: {entity_w9_path}")
    logger.info(f"Entity Payee Auth path: {entity_payee_path}")

    for page_num in range(total_pages):
        # Skip page 11 (W-9) only if entity W-9 is provided
        if page_num == 11 and entity_w9_path:
            logger.info(f"Skipping page 12 (W-9 replaced by entity upload)")
            continue
        # Skip pages 12-13 (Payee Auth) only if entity payee auth is provided
        if page_num in (12, 13) and entity_payee_path:
            logger.info(f"Skipping page {page_num + 1} (Payee Auth replaced by entity upload)")
            continue

        page = reader.pages[page_num]

        # Create text overlay for this page
        overlay_bytes = _create_text_overlay(page_num, form_data)
        if overlay_bytes:
            overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
            overlay_page = overlay_reader.pages[0]
            page.merge_page(overlay_page)

        writer.add_page(page)

    # Append entity W-9 PDF
    if entity_w9_path:
        logger.info(f"Appending entity W-9 from: {entity_w9_path}")
        _append_pdf(writer, entity_w9_path, "W-9")

    # Append entity Payee Authorization PDF
    if entity_payee_path:
        logger.info(f"Appending entity Payee Auth from: {entity_payee_path}")
        _append_pdf(writer, entity_payee_path, "Payee Auth")

    # Write final PDF to bytes
    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    logger.info(f"Generated packet: {len(writer.pages)} pages")
    return output.read()


def _derive_fields(form_data: dict):
    """Fill in composite/derived fields from existing data."""
    # Build full unit address if components exist
    if "unit_address" not in form_data or not form_data["unit_address"]:
        parts = [
            form_data.get("property_address", ""),
        ]
        city_state_zip = ", ".join(filter(None, [
            form_data.get("city", ""),
            form_data.get("state", ""),
        ]))
        if form_data.get("zip_code"):
            city_state_zip += " " + form_data["zip_code"]
        if city_state_zip.strip():
            parts.append(city_state_zip.strip())
        form_data["unit_address"] = ", ".join(filter(None, parts))

    # Default signature date to today
    if "signature_date" not in form_data or not form_data["signature_date"]:
        from datetime import date
        form_data["signature_date"] = date.today().strftime("%m/%d/%Y")

    if "tenant_sign_date" not in form_data or not form_data["tenant_sign_date"]:
        form_data["tenant_sign_date"] = form_data.get("signature_date", "")

    # Owner title defaults to "Partner"
    if "owner_title" not in form_data or not form_data["owner_title"]:
        form_data["owner_title"] = "Partner"

    # Derive owner initials from owner_name (e.g. "Alexander Hatzis" → "AH")
    owner_name = form_data.get("owner_name", "")
    if owner_name and ("owner_initials" not in form_data or not form_data["owner_initials"]):
        form_data["owner_initials"] = "".join(
            w[0].upper() for w in owner_name.split() if w
        )

    # Always check Initial Occupancy and Barrier-Free Yes
    form_data["initial_occupancy"] = "true"
    form_data["barrier_free_yes"] = "true"

    # Always check lead paint checkboxes
    form_data["lead_completed_statement"] = "true"   # P6: 3rd box
    form_data["lead_pre1978_ongoing"] = "true"        # P9: 3rd box

    # Map property_type to building type checkbox
    ptype = (form_data.get("property_type") or "").lower().strip()
    btype_map = {
        "single family": "btype_single_family",
        "duplex": "btype_duplex",
        "triplex": "btype_triplex",
        "fourplex": "btype_fourplex",
        "townhouse": "btype_townhouse",
        "high-rise": "btype_highrise",
        "low-rise": "btype_lowrise",
        "manufactured home": "btype_manufactured",
        "multi-family": "btype_fourplex",
        "apartment": "btype_lowrise",
    }
    btype_field = btype_map.get(ptype)
    if btype_field:
        form_data[btype_field] = "true"


def _append_pdf(writer: PdfWriter, pdf_path: str, label: str):
    """Append all pages from an external PDF file to the writer."""
    try:
        if pdf_path.startswith(("http://", "https://")):
            import urllib.request
            logger.info(f"Downloading {label} from URL: {pdf_path[:80]}...")
            req = urllib.request.Request(pdf_path, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                pdf_bytes = resp.read()
            logger.info(f"Downloaded {label}: {len(pdf_bytes)} bytes")
            reader = PdfReader(io.BytesIO(pdf_bytes))
        else:
            if not os.path.exists(pdf_path):
                logger.error(f"{label} file not found at: {pdf_path}")
                return
            reader = PdfReader(pdf_path)

        for page in reader.pages:
            writer.add_page(page)
        logger.info(f"Appended {len(reader.pages)} {label} pages")
    except Exception as e:
        logger.error(f"Failed to append {label} from {pdf_path}: {e}", exc_info=True)
