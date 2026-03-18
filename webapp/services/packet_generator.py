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
    # Exact from user-filled PDF annotations
    # ------------------------------------------------------------------
    1: [
        ("tenant_name",    187, 450, 12),
        ("tenant_email",   181, 490, 12),
        ("owner_name",     187, 573, 12),    # exact
        ("owner_email",    181, 610, 12),    # exact
    ],

    # ------------------------------------------------------------------
    # P4 (page 3): Property Owner Checklist p1
    # All coordinates exact from user-filled PDF
    # ------------------------------------------------------------------
    3: [
        ("tenant_name",         113, 130, 11),   # exact
        ("unit_address",        108, 154, 10),   # exact
        ("city",                 71, 178, 11),   # exact
        ("state",               418, 175, 11),   # exact
        ("zip_code",            491, 175, 11),   # exact
        ("bedrooms",            150, 200, 11),   # exact
        ("bathrooms",           341, 200, 11),   # exact
        ("year_built",          271, 226, 11),   # exact
        ("proposed_rent",       507, 226, 11),   # exact
        ("county",              430, 247, 10),   # exact
        # Property Owner section
        ("entity_name",         124, 589, 10),   # exact
        ("ein",                 510, 589, 10),   # exact
        ("owner_name",          115, 611, 11),   # exact
        ("owner_phone",          84, 637, 10),   # exact
        ("owner_email",         354, 634, 10),   # exact
    ],

    # ------------------------------------------------------------------
    # P5 (page 4): Property Owner Checklist p2 — owner certification
    # Exact from user-filled PDF
    # ------------------------------------------------------------------
    4: [
        ("owner_name",          262, 480, 11),   # exact
        ("owner_title",         215, 503, 11),   # exact
        ("owner_name__sig",     100, 519, 14),   # signature between title and date
        ("signature_date",      477, 529, 11),   # exact
    ],

    # ------------------------------------------------------------------
    # P6 (page 5): HUD-52517 p2 — certifications, signatures at bottom
    # Exact from user-filled PDF
    # ------------------------------------------------------------------
    5: [
        ("owner_name",             48, 544, 10),   # exact
        ("tenant_name",           345, 544, 10),   # same y, right column
        ("owner_name__sig",        48, 570, 12),   # between name and address
        ("owner_mailing_address",  40, 637, 9),    # exact
        ("owner_phone",            56, 683, 10),   # exact
        ("signature_date",        229, 683, 10),   # exact
        ("tenant_sign_date",      490, 683, 10),   # same y, right column
    ],

    # ------------------------------------------------------------------
    # P7 (page 6): HUD-52517 p1 — Request for Tenancy Approval
    # Exact from user-filled PDF
    # ------------------------------------------------------------------
    6: [
        ("unit_address",        325, 236, 10),   # same row as PHA name
        ("lease_start_date",     67, 272, 10),   # exact
        ("bedrooms",            188, 272, 10),   # exact
        ("year_built",          276, 272, 10),   # exact
        ("proposed_rent",       354, 272, 10),   # exact
        ("security_deposit",    430, 272, 10),   # exact
        ("date_available",      517, 272, 10),   # exact
        # Utility responsibilities — T (tenant) or O (owner)
        ("util_heating_paid",   525, 512, 10),   # exact
        ("util_cooking_paid",   525, 538, 10),   # exact
        ("util_water_heat_paid", 525, 562, 10),  # exact
        ("util_other_elec_paid", 525, 583, 10),  # exact
        ("util_water_paid",     525, 601, 10),   # exact
        ("util_sewer_paid",     525, 620, 10),   # exact
        ("util_trash_paid",     525, 640, 10),   # exact
        ("util_ac_paid",        525, 658, 10),   # exact
        ("util_other_paid",     525, 680, 10),   # exact
        ("util_fridge_paid",    524, 717, 10),   # exact
        ("util_range_paid",     524, 740, 10),   # exact
    ],

    # ------------------------------------------------------------------
    # P8 (page 7): Lead-Based Paint Disclosure
    # Exact from user-filled PDF
    # ------------------------------------------------------------------
    7: [
        ("property_address",     100, 80, 10),
        # Owner/Landlord initials on lines (a), (b), and (e)
        ("owner_initials",        37, 197, 10),   # line (a) — lead paint presence
        ("owner_initials",        37, 305, 10),   # line (b) — records available
        ("owner_initials",        37, 500, 10),   # line (e) — agent acknowledgment
        # Certification signatures at bottom
        ("owner_name__sig",       48, 595, 12),   # Owner/Landlord Signature line
        ("owner_name__sig",       48, 622, 12),   # Owner's Agent Signature line
        ("signature_date",       462, 605, 10),   # exact — owner date
        ("tenant_sign_date",     462, 629, 10),   # exact — tenant date
    ],

    # ------------------------------------------------------------------
    # P9 (page 8): Owner Certification — Lead Paint
    # Exact from user-filled PDF
    # ------------------------------------------------------------------
    8: [
        ("property_address",     105, 113, 10),   # exact
        ("owner_name__sig",      164, 547, 12),   # signature above name line
        ("owner_name",           164, 557, 10),   # exact
        ("signature_date",       433, 557, 10),   # exact
    ],

    # ------------------------------------------------------------------
    # P11 (page 10): HCV Rules p2 — signatures at very bottom
    # Owner fields exact from user-filled PDF
    # ------------------------------------------------------------------
    10: [
        ("tenant_name",          183, 650, 10),   # estimated
        ("tenant_sign_date",     486, 665, 10),   # estimated
        ("owner_name",           280, 695, 10),   # Landlord/Owner Printed Name row
        ("owner_name__sig",      183, 718, 11),   # Landlord/Owner Signature row
        ("signature_date",       486, 718, 10),   # same row as signature
    ],

    # Pages 12-14 (W-9, Payee Auth) are always replaced by entity uploads — no field mapping needed.
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
    # Y values exact from user-filled PDF, X values for unchecked
    # options estimated from form layout
    # ------------------------------------------------------------------
    3: [
        # Transaction type — exact (44, 87)
        ("initial_occupancy",        44, 87, 9),
        # Barrier-Free Unit — Yes — exact (131, 252)
        ("barrier_free_yes",        131, 252, 8),
        # Building Type — Single Family exact (49, 379), others spaced ~14pt
        ("btype_highrise",           49, 295, 8),
        ("btype_lowrise",            49, 309, 8),
        ("btype_townhouse",          49, 323, 8),
        ("btype_duplex",             49, 337, 8),
        ("btype_triplex",            49, 351, 8),
        ("btype_fourplex",           49, 365, 8),
        ("btype_single_family",      49, 379, 8),   # exact
        ("btype_manufactured",       49, 393, 8),
        # Features — Y values exact from user-filled PDF
        # Water row y=421
        ("feat_water_city",         131, 421, 7),   # exact
        ("feat_water_well",         200, 421, 7),
        # Sewer row y=436
        ("feat_sewer_public",       131, 436, 7),   # exact
        ("feat_sewer_septic",       200, 436, 7),
        # Cooling System row y=451
        ("feat_cool_central",       131, 451, 7),   # exact
        ("feat_cool_window",        195, 451, 7),
        ("feat_cool_none",          260, 451, 7),
        # Heating System row y=465
        ("feat_heat_baseboard",     131, 465, 7),
        ("feat_heat_boiler",        195, 465, 7),
        ("feat_heat_central",       250, 465, 7),
        ("feat_heat_furnace",       321, 465, 7),   # exact
        # Indoor row y=485
        ("feat_indoor_cable",        62, 485, 7),
        ("feat_indoor_ceiling_fan", 128, 485, 7),
        ("feat_indoor_dryer",       178, 485, 7),
        ("feat_indoor_washer",      218, 485, 7),
        ("feat_indoor_hookups",     268, 485, 7),
        ("feat_indoor_laundry",     390, 485, 7),   # exact x from user
        # Kitchen row y=504
        ("feat_kitchen_dishwasher",  82, 504, 7),
        ("feat_kitchen_disposal",   150, 504, 7),
        ("feat_kitchen_microwave",  243, 504, 7),
        ("feat_kitchen_fridge",     399, 504, 7),   # exact x from user
        ("feat_kitchen_range",      486, 504, 7),   # exact x from user
        # Outdoor row y=519 (estimated)
        ("feat_outdoor_balcony",     82, 519, 7),
        ("feat_outdoor_pool",       138, 519, 7),
        ("feat_outdoor_gated",      186, 519, 7),
        # Parking row y=533 (estimated)
        ("feat_parking_garage",      78, 533, 7),
        ("feat_parking_1car",       115, 533, 7),
        ("feat_parking_2car",       152, 533, 7),
        ("feat_parking_3car",       192, 533, 7),
        # Maintenance row y=547 (estimated)
        ("feat_maint_lawn",          82, 547, 7),
        ("feat_maint_pest",         125, 547, 7),
        ("feat_maint_trash",        192, 547, 7),
        # Check Here if Same as Property Owner — exact (216, 665)
        ("mgmt_same_as_owner",      216, 665, 8),
    ],

    # ------------------------------------------------------------------
    # P7 (page 6): HUD-52517 p1 — Structure type (section 9) & fuel type
    # Exact from user-filled PDF
    # ------------------------------------------------------------------
    6: [
        # Structure type — section 9, Single Family exact at (37, 315)
        ("stype_single_family",   37, 315, 8),   # exact
        ("stype_duplex",          37, 335, 8),
        ("stype_townhouse",       37, 355, 8),
        ("stype_lowrise",         37, 375, 8),
        ("stype_highrise",        37, 395, 8),
        ("stype_manufactured",    37, 415, 8),
        # Fuel type — Natural gas checkboxes (x=129)
        ("fuel_heating_gas",     129, 512, 7),   # exact row as Heating
        ("fuel_cooking_gas",     129, 538, 7),   # exact row as Cooking
        ("fuel_water_heat_gas",  129, 562, 7),   # exact row as Water Heating
    ],

    # P6 (page 5): HUD-52517 p2 — "c. Check one of the following:"
    # Exact from user-filled PDF (321, 209)
    # ------------------------------------------------------------------
    5: [
        ("lead_completed_statement", 321, 209, 8),   # exact
    ],

    # P8 (page 7): Lead-Based Paint Disclosure — checkboxes
    7: [
        ("lead_paint_known",         95, 274, 9),    # exact
        ("lead_paint_records",       95, 387, 9),    # exact
    ],

    # P9 (page 8): Owner Certification — Lead Paint
    8: [
        ("lead_pre1978_ongoing",     60, 312, 10),   # exact
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
    form_data["lead_paint_known"] = "true"
    form_data["lead_paint_records"] = "true"
    form_data["mgmt_same_as_owner"] = "true"

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

    # Structure type on page 7 (HUD-52517 p1, section 9) — same logic, stype_ prefix
    stype_map = {
        "single family": "stype_single_family",
        "duplex": "stype_duplex",
        "townhouse": "stype_townhouse",
        "high-rise": "stype_highrise",
        "low-rise": "stype_lowrise",
        "manufactured home": "stype_manufactured",
        "multi-family": "stype_lowrise",
        "apartment": "stype_lowrise",
        "triplex": "stype_townhouse",
        "fourplex": "stype_townhouse",
    }
    stype_field = stype_map.get(ptype)
    if stype_field:
        form_data[stype_field] = "true"

    # Default utility responsibilities: T for all, O for Refrigerator & Range
    util_defaults = {
        "util_heating_paid": "T",
        "util_cooking_paid": "T",
        "util_water_heat_paid": "T",
        "util_other_elec_paid": "T",
        "util_water_paid": "T",
        "util_sewer_paid": "T",
        "util_trash_paid": "T",
        "util_ac_paid": "T",
        "util_other_paid": "T",
        "util_fridge_paid": "O",
        "util_range_paid": "O",
    }
    for field, default in util_defaults.items():
        if field not in form_data or not form_data[field]:
            form_data[field] = default

    # Natural gas fuel type for Heating, Cooking, Water Heating
    form_data["fuel_heating_gas"] = "true"
    form_data["fuel_cooking_gas"] = "true"
    form_data["fuel_water_heat_gas"] = "true"


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
