"""MSHDA Landlord Packet PDF generator.

Overlays text onto a scanned (image-based) blank MSHDA packet PDF.
Uses PyMuPDF (fitz) to insert text directly onto pages, then pypdf
to append entity-specific W-9 and Payee Authorization PDFs.

The blank packet template should be placed at:
    webapp/static/templates/mshda_blank_packet.pdf
"""

import io
import logging
import os
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# Path to the blank MSHDA packet (20-page scanned PDF)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BLANK_PACKET_PATH = STATIC_DIR / "templates" / "mshda_blank_packet.pdf"
FONTS_DIR = STATIC_DIR / "fonts"

# Page dimensions in points
PAGE_W, PAGE_H = 612, 792

# Load cursive font for signatures
_CURSIVE_FONT_PATH = FONTS_DIR / "GreatVibes-Regular.ttf"
CURSIVE_FONT_AVAILABLE = _CURSIVE_FONT_PATH.exists()
if CURSIVE_FONT_AVAILABLE:
    logger.info("GreatVibes cursive font found for signatures")

# =============================================================================
# Field coordinate map  —  PyMuPDF / fitz coordinate system
# =============================================================================
# Origin at TOP-LEFT, y increases DOWNWARD.
# Each entry: page_number (0-indexed) -> list of (field_name, x, y, font_size)
# Fields ending with "__sig" render in cursive and look up the base field name.
#
# To convert old ReportLab coords: fitz_y = 792 - rl_y
# =============================================================================

FIELD_MAP = {
    # ------------------------------------------------------------------
    # P2 (page 1): Communications notice
    # ------------------------------------------------------------------
    1: [
        ("tenant_name",    205, 450, 12),
        ("tenant_email",   205, 490, 12),
        ("owner_name",     205, 568, 12),
        ("owner_email",    215, 605, 12),
    ],

    # ------------------------------------------------------------------
    # P4 (page 3): Property Owner Checklist p1
    # Measured from 400 DPI grid analysis (fitz coords)
    # ------------------------------------------------------------------
    3: [
        ("tenant_name",         120, 130, 11),
        ("unit_address",        105, 150, 10),
        ("city",                 50, 170, 11),
        ("state",               425, 170, 11),
        ("zip_code",            482, 170, 11),
        ("bedrooms",            155, 190, 11),
        ("bathrooms",           355, 190, 11),
        ("year_built",          310, 210, 11),
        ("proposed_rent",       510, 210, 11),
        # Property Owner section — baselines aligned with label text
        ("entity_name",        155, 584, 10),
        ("ein",                490, 584, 10),
        ("owner_name",         120, 606, 11),
        ("owner_phone",        100, 628, 10),
        ("owner_email",        395, 628, 10),
    ],

    # ------------------------------------------------------------------
    # P5 (page 4): Property Owner Checklist p2 — owner certification
    # Measured: Printed Name label ~fitz 475, Title ~498, Signature ~523
    # Text placed in blank space ABOVE each label
    # ------------------------------------------------------------------
    4: [
        ("owner_name",          100, 466, 11),   # Above "Printed Name" label
        ("owner_title",         100, 489, 11),   # Above "Title" label
        ("owner_name__sig",     100, 514, 14),   # Above "Signature:" label
        ("signature_date",      430, 514, 11),   # Date field on Signature row
    ],

    # ------------------------------------------------------------------
    # P6 (page 5): HUD-52517 p2 — certifications, signatures at bottom
    # ------------------------------------------------------------------
    5: [
        ("owner_name",             60, 537, 10),
        ("tenant_name",           345, 537, 10),
        ("owner_name__sig",        60, 560, 12),
        ("owner_mailing_address",  60, 592, 9),
        ("owner_phone",            60, 629, 10),
        ("signature_date",        260, 629, 10),
        ("tenant_sign_date",      490, 629, 10),
    ],

    # ------------------------------------------------------------------
    # P7 (page 6): HUD-52517 p1 — Request for Tenancy Approval
    # ------------------------------------------------------------------
    6: [
        ("unit_address",        325, 372, 10),
        ("lease_start_date",     60, 424, 10),
        ("bedrooms",            200, 424, 10),
        ("year_built",          265, 424, 10),
        ("proposed_rent",       350, 424, 10),
        ("utility_allowance",   430, 424, 10),
    ],

    # ------------------------------------------------------------------
    # P8 (page 7): Lead-Based Paint Disclosure
    # ------------------------------------------------------------------
    7: [
        ("property_address",     100, 80, 10),
        ("owner_initials",        55, 174, 10),
        ("owner_initials",        55, 272, 10),
        ("owner_initials",        55, 414, 10),
        ("owner_name__sig",      120, 554, 12),
        ("signature_date",       460, 554, 10),
    ],

    # ------------------------------------------------------------------
    # P9 (page 8): Owner Certification — Lead Paint
    # ------------------------------------------------------------------
    8: [
        ("property_address",     300, 92, 10),
        ("owner_name__sig",      120, 524, 12),
        ("owner_name",           120, 544, 10),
        ("signature_date",       370, 544, 10),
    ],

    # ------------------------------------------------------------------
    # P11 (page 10): HCV Rules p2 — signatures at very bottom
    # ------------------------------------------------------------------
    10: [
        ("tenant_name",          160, 700, 10),
        ("tenant_sign_date",     490, 715, 10),
        ("owner_name__sig",      160, 735, 11),
        ("signature_date",       490, 750, 10),
    ],

    # ------------------------------------------------------------------
    # P13 (page 12): MSHDA Payee Authorization p1
    # ------------------------------------------------------------------
    12: [
        ("tenant_name",            410, 44, 10),
        ("entity_name",             55, 164, 10),
        ("owner_mailing_address",   55, 340, 10),
        ("owner_phone",            100, 420, 10),
        ("owner_email",            100, 435, 10),
    ],

    # ------------------------------------------------------------------
    # P14 (page 13): Payee Authorization p2 — bank info
    # ------------------------------------------------------------------
    13: [
        ("bank_name",              200, 64, 11),
        ("bank_routing_number",    200, 120, 11),
        ("bank_account_number",    200, 137, 11),
        ("owner_name__sig",        255, 370, 12),
        ("signature_date",         490, 387, 11),
    ],
}

# =============================================================================
# Checkbox coordinate map  —  fitz coords (top-left origin)
# =============================================================================
# Each entry: page_number -> list of (field_name, x, y, size)
# An "X" is drawn if form_data[field_name] is truthy.
# =============================================================================

CHECKBOX_MAP = {
    # ------------------------------------------------------------------
    # P4 (page 3): Property Owner Checklist p1
    # Measured from 400 DPI grid analysis
    # ------------------------------------------------------------------
    3: [
        # Transaction type (top of page)
        ("initial_occupancy",        31, 83, 9),
        # Barrier-Free Unit — Yes checkbox
        ("barrier_free_yes",        143, 245, 8),
        # Building Type (check one based on property_type)
        ("btype_highrise",           31, 293, 8),
        ("btype_lowrise",            31, 306, 8),
        ("btype_townhouse",          31, 319, 8),
        ("btype_duplex",             31, 332, 8),
        ("btype_triplex",            31, 345, 8),
        ("btype_fourplex",           31, 358, 8),
        ("btype_single_family",      31, 371, 8),
        ("btype_manufactured",       31, 384, 8),
        # Features Available — Water
        ("feat_water_city",          98, 437, 7),
        ("feat_water_well",         168, 437, 7),
        # Sewer
        ("feat_sewer_public",        82, 445, 7),
        ("feat_sewer_septic",       165, 445, 7),
        # Cooling System
        ("feat_cool_central",       105, 454, 7),
        ("feat_cool_window",        160, 454, 7),
        ("feat_cool_none",          218, 454, 7),
        # Heating System
        ("feat_heat_baseboard",     105, 463, 7),
        ("feat_heat_boiler",        165, 463, 7),
        ("feat_heat_central",       210, 463, 7),
        ("feat_heat_furnace",       262, 463, 7),
        # Indoor
        ("feat_indoor_cable",        62, 478, 7),
        ("feat_indoor_ceiling_fan", 128, 478, 7),
        ("feat_indoor_dryer",       178, 478, 7),
        ("feat_indoor_washer",      218, 478, 7),
        ("feat_indoor_hookups",     268, 478, 7),
        ("feat_indoor_laundry",     382, 478, 7),
        # Kitchen
        ("feat_kitchen_dishwasher",  82, 497, 7),
        ("feat_kitchen_disposal",   150, 497, 7),
        ("feat_kitchen_microwave",  243, 497, 7),
        ("feat_kitchen_fridge",     310, 497, 7),
        ("feat_kitchen_range",      388, 497, 7),
        # Outdoor
        ("feat_outdoor_balcony",     82, 513, 7),
        ("feat_outdoor_pool",       138, 513, 7),
        ("feat_outdoor_gated",      186, 513, 7),
        # Parking
        ("feat_parking_garage",      78, 525, 7),
        ("feat_parking_1car",       115, 525, 7),
        ("feat_parking_2car",       152, 525, 7),
        ("feat_parking_3car",       192, 525, 7),
        # Maintenance
        ("feat_maint_lawn",          82, 537, 7),
        ("feat_maint_pest",         125, 537, 7),
        ("feat_maint_trash",        192, 537, 7),
    ],

    # ------------------------------------------------------------------
    # P6 (page 5): HUD-52517 p2 — "c. Check one of the following:"
    # ------------------------------------------------------------------
    5: [
        ("lead_completed_statement", 477, 195, 8),
    ],

    # P9 (page 8): Owner Certification — Lead Paint
    8: [
        ("lead_pre1978_ongoing",     48, 310, 10),
    ],
}


def _insert_fields(page: fitz.Page, page_num: int, form_data: dict):
    """Insert text fields and checkboxes directly onto a fitz page."""
    text_fields = FIELD_MAP.get(page_num, [])
    checkbox_fields = CHECKBOX_MAP.get(page_num, [])

    if not text_fields and not checkbox_fields:
        return

    # Load cursive font if available
    sig_fontname = "helv"
    if CURSIVE_FONT_AVAILABLE:
        try:
            page.insert_font(fontname="GreatVibes", fontfile=str(_CURSIVE_FONT_PATH))
            sig_fontname = "GreatVibes"
        except Exception:
            pass

    # Draw text fields
    for field_name, x, y, font_size in text_fields:
        if field_name.endswith("__sig"):
            actual_field = field_name[:-5]
            value = form_data.get(actual_field, "")
            if value:
                page.insert_text(
                    fitz.Point(x, y),
                    str(value),
                    fontsize=font_size,
                    fontname=sig_fontname,
                    color=(0, 0, 0),
                )
        else:
            value = form_data.get(field_name, "")
            if value:
                page.insert_text(
                    fitz.Point(x, y),
                    str(value),
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )

    # Draw checkbox X marks
    for field_name, x, y, size in checkbox_fields:
        value = form_data.get(field_name)
        if value and str(value).lower() in ("true", "1", "yes", "on"):
            page.insert_text(
                fitz.Point(x, y),
                "X",
                fontsize=size,
                fontname="helv",
                color=(0, 0, 0),
            )


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

    _derive_fields(form_data)

    # Open with fitz and insert text directly onto pages
    doc = fitz.open(template_path)
    total_pages = len(doc)
    logger.info(f"Processing {total_pages}-page blank packet")

    # Track which pages to skip (replaced by entity uploads)
    skip_pages = set()
    if entity_w9_path:
        skip_pages.add(11)  # Page 12 (W-9)
    if entity_payee_path:
        skip_pages.add(12)  # Page 13 (Payee Auth p1)
        skip_pages.add(13)  # Page 14 (Payee Auth p2)

    # Insert text on all non-skipped pages
    for page_num in range(total_pages):
        if page_num in skip_pages:
            logger.info(f"Skipping page {page_num + 1} (replaced by entity upload)")
            continue
        _insert_fields(doc[page_num], page_num, form_data)

    # Save the modified PDF to bytes
    modified_bytes = doc.tobytes()
    doc.close()

    # Use pypdf to remove skipped pages and append entity PDFs
    reader = PdfReader(io.BytesIO(modified_bytes))
    writer = PdfWriter()

    for page_num in range(len(reader.pages)):
        if page_num not in skip_pages:
            writer.add_page(reader.pages[page_num])

    # Append entity W-9 PDF
    if entity_w9_path:
        logger.info(f"Appending entity W-9 from: {entity_w9_path}")
        _append_pdf(writer, entity_w9_path, "W-9")

    # Append entity Payee Authorization PDF
    if entity_payee_path:
        logger.info(f"Appending entity Payee Auth from: {entity_payee_path}")
        _append_pdf(writer, entity_payee_path, "Payee Auth")

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    logger.info(f"Generated packet: {len(writer.pages)} pages")
    return output.read()


def _derive_fields(form_data: dict):
    """Fill in composite/derived fields from existing data."""
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

    if "signature_date" not in form_data or not form_data["signature_date"]:
        from datetime import date
        form_data["signature_date"] = date.today().strftime("%m/%d/%Y")

    if "tenant_sign_date" not in form_data or not form_data["tenant_sign_date"]:
        form_data["tenant_sign_date"] = form_data.get("signature_date", "")

    if "owner_title" not in form_data or not form_data["owner_title"]:
        form_data["owner_title"] = "Partner"

    owner_name = form_data.get("owner_name", "")
    if owner_name and ("owner_initials" not in form_data or not form_data["owner_initials"]):
        form_data["owner_initials"] = "".join(
            w[0].upper() for w in owner_name.split() if w
        )

    form_data["initial_occupancy"] = "true"
    form_data["barrier_free_yes"] = "true"
    form_data["lead_completed_statement"] = "true"
    form_data["lead_pre1978_ongoing"] = "true"

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
