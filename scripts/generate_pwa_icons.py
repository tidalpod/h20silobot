#!/usr/bin/env python3
"""Generate PWA icons from logo.png.

Usage:
    python scripts/generate_pwa_icons.py

Requires: Pillow (pip install Pillow)
"""

from pathlib import Path

from PIL import Image

SIZES = [72, 96, 128, 144, 152, 192, 384, 512]
LOGO_PATH = Path(__file__).resolve().parent.parent / "webapp" / "static" / "images" / "logo.png"
OUTPUT_DIR = LOGO_PATH.parent / "icons"


def generate_icons():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logo = Image.open(LOGO_PATH).convert("RGBA")

    for size in SIZES:
        resized = logo.resize((size, size), Image.LANCZOS)
        out_path = OUTPUT_DIR / f"icon-{size}x{size}.png"
        resized.save(out_path, "PNG")
        print(f"  Created {out_path.name}")

    # Maskable icon: 512x512 with safe-zone padding (10% on each side)
    maskable_size = 512
    padding = int(maskable_size * 0.1)  # 10% padding
    inner_size = maskable_size - (padding * 2)
    canvas = Image.new("RGBA", (maskable_size, maskable_size), (255, 255, 255, 255))
    inner = logo.resize((inner_size, inner_size), Image.LANCZOS)
    canvas.paste(inner, (padding, padding), inner)
    mask_path = OUTPUT_DIR / "icon-512x512-maskable.png"
    canvas.save(mask_path, "PNG")
    print(f"  Created {mask_path.name} (maskable)")

    print(f"\nDone! {len(SIZES) + 1} icons saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    generate_icons()
