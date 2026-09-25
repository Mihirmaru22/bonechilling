"""ocr.py — reads printed text off an X-ray film photo."""
import sys
from pathlib import Path

from PIL import Image, ImageOps
import pytesseract


def ocr_lines(image_path, band_fraction=0.15):
    """Return non-empty text lines from the film's bottom label band."""
    img = Image.open(image_path)
    w, h = img.size

    # 1. crop the bottom band where hospitals print labels
    band = img.crop((0, int(h * (1 - band_fraction)), w, h))

    # 2. upscale 3x — tesseract reads big pixels far better than tiny ones
    band = band.resize((band.width * 3, band.height * 3), Image.LANCZOS)

    # 3. grayscale + stretch contrast so white-on-black text pops
    band = band.convert("L")
    band = ImageOps.autocontrast(band)

    # 4. read. psm 6 = "assume one uniform block of text"
    raw = pytesseract.image_to_string(band, config="--psm 6")

    # 5. clean: strip whitespace, drop empty lines
    return [line.strip() for line in raw.splitlines() if line.strip()]


if __name__ == "__main__":
    # SELF-TEST: python ocr.py data/elbow1.jpg [band_fraction]
    if len(sys.argv) < 2:
        print("usage: python ocr.py <image> [band_fraction]")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"file not found: {path}")
        sys.exit(1)

    frac = float(sys.argv[2]) if len(sys.argv) > 2 else 0.15
    lines = ocr_lines(path, frac)

    print(f"{len(lines)} lines found:")
    for i, line in enumerate(lines, 1):
        print(f"{i:2d} | {line}")