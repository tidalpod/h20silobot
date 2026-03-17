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
from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# Path to the blank MSHDA packet (20-page scanned PDF)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
BLANK_PACKET_PATH = STATIC_DIR / "templates" / "mshda_blank_packet.pdf"

# Letter page dimensions in points (8.5 x 11 inches)
PAGE_W, PAGE_H = letter  # 612 x 792

# =============================================================================
# Field coordinate map
# =============================================================================
# Each entry: page_number (0-indexed) -> list of (field_name, x, y, font_size)
# Coordinates are in points from bottom-left (ReportLab convention).
# These are initial approximations — calibrate with test prints.
#
# Pages are 0-indexed to match pypdf page numbering.
# =============================================================================

FIELD_MAP = {
    # ------------------------------------------------------------------
    # P2 (page 1): Communications notice
    # Calibrated from grid: fields at y≈340, 300, 222, 187
    # ------------------------------------------------------------------
    1: [
        ("tenant_name",    205, 342, 12),
        ("tenant_email",   205, 302, 12),
        ("owner_name",     205, 224, 12),
        ("owner_email",    215, 187, 12),
    ],

    # ------------------------------------------------------------------
    # P4 (page 3): Property Owner Checklist p1
    # Calibrated from grid: rows at y≈665, 645, 625, 605, 585, 205, 185, 165
    # ------------------------------------------------------------------
    3: [
        ("tenant_name",         145, 665, 11),
        ("unit_address",        145, 645, 10),
        ("city",                 90, 625, 11),
        ("state",               445, 625, 11),
        ("zip_code",            510, 625, 11),
        ("bedrooms",            175, 605, 11),
        ("bathrooms",           345, 605, 11),
        ("year_built",          335, 585, 11),
        ("proposed_rent",       515, 585, 11),
        ("entity_name",        160, 205, 10),
        ("owner_name",         145, 185, 11),
        ("owner_phone",        105, 165, 10),
        ("owner_email",        420, 165, 10),
    ],

    # ------------------------------------------------------------------
    # P5 (page 4): Property Owner Checklist p2 — owner certification
    # Calibrated: printed name at y≈260, signature at y≈228
    # ------------------------------------------------------------------
    4: [
        ("owner_name",     100, 260, 11),
        ("signature_date", 400, 228, 11),
    ],

    # ------------------------------------------------------------------
    # P6 (page 5): HUD-52517 p2 — certifications, signatures at bottom
    # Calibrated: owner name y≈103, tenant name y≈103, dates y≈50
    # ------------------------------------------------------------------
    5: [
        ("owner_name",         60, 103, 10),
        ("tenant_name",       345, 103, 10),
        ("signature_date",    230,  50, 10),
        ("tenant_sign_date",  495,  50, 10),
    ],

    # ------------------------------------------------------------------
    # P7 (page 6): HUD-52517 p1 — Request for Tenancy Approval
    # Calibrated: address y≈420, items 3-8 y≈368, rent fields y≈298
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
    # Calibrated: address y≈712, signature y≈203
    # ------------------------------------------------------------------
    7: [
        ("property_address", 100, 712, 10),
        ("owner_name",       100, 203, 10),
        ("signature_date",   370, 203, 10),
    ],

    # ------------------------------------------------------------------
    # P9 (page 8): Owner Certification — Lead Paint
    # Calibrated: address y≈728, printed name y≈312
    # ------------------------------------------------------------------
    8: [
        ("property_address", 300, 728, 10),
        ("owner_name",       160, 312, 10),
        ("signature_date",   435, 312, 10),
    ],

    # ------------------------------------------------------------------
    # P11 (page 10): HCV Rules p2 — signatures at very bottom
    # Calibrated: tenant name y≈92, tenant date y≈77, owner y≈57, date y≈42
    # ------------------------------------------------------------------
    10: [
        ("tenant_name",       160,  92, 10),
        ("tenant_sign_date",  490,  77, 10),
        ("owner_name",        160,  57, 10),
        ("signature_date",    490,  42, 10),
    ],

    # ------------------------------------------------------------------
    # P13 (page 12): MSHDA Payee Authorization p1
    # Calibrated: payee name y≈628, address y≈452, phone y≈372, email y≈357
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
    # Calibrated: bank name y≈728, routing y≈672, acct y≈655, sig y≈405
    # ------------------------------------------------------------------
    13: [
        ("bank_name",           200, 728, 11),
        ("bank_routing_number", 200, 672, 11),
        ("bank_account_number", 200, 655, 11),
        ("owner_name",          255, 422, 11),
        ("signature_date",      490, 405, 11),
    ],
}

# Checkbox field map: page -> list of (field_name, x, y, size)
# Checkbox coordinates need per-page calibration — left empty for now.
# Generate a test packet to identify exact checkbox positions.
CHECKBOX_MAP = {}

# Pages to SKIP in the base PDF (0-indexed) when entity docs are appended.
# Page 11 = W-9 (replaced by entity upload)
# Pages 12-13 = Payee Auth (replaced by entity upload)
SKIP_PAGES = {11, 12, 13}


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

    # Draw text fields (bold for visibility on scanned backgrounds)
    for field_name, x, y, font_size in text_fields:
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

    for page_num in range(total_pages):
        # Skip pages replaced by entity uploads
        if page_num in SKIP_PAGES and (entity_w9_path or entity_payee_path):
            logger.debug(f"Skipping page {page_num + 1} (replaced by entity doc)")
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
        _append_pdf(writer, entity_w9_path, "W-9")

    # Append entity Payee Authorization PDF
    if entity_payee_path:
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


def _append_pdf(writer: PdfWriter, pdf_path: str, label: str):
    """Append all pages from an external PDF file to the writer."""
    try:
        if pdf_path.startswith(("http://", "https://")):
            # Download from URL (R2 or external)
            import urllib.request
            with urllib.request.urlopen(pdf_path) as resp:
                pdf_bytes = resp.read()
            reader = PdfReader(io.BytesIO(pdf_bytes))
        else:
            reader = PdfReader(pdf_path)

        for page in reader.pages:
            writer.add_page(page)
        logger.info(f"Appended {len(reader.pages)} {label} pages")
    except Exception as e:
        logger.error(f"Failed to append {label} from {pdf_path}: {e}")
