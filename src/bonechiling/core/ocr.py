"""ocr.py — read the printed patient label off a film (pluggable backend).

Refactored from the original root ocr.py:
- Operates on a PIL image OR a path, so a film-detection step can hand it a
  cropped/warped film instead of the raw phone photo (the original always read
  the bottom 15% of the whole photo, which misses the label on tilted photos).
- Tries the label band at the BOTTOM and the TOP (hospitals print it either
  place) and keeps whichever yields more legible text.
- Backend is pluggable: Tesseract today (zero-install default), RapidOCR later
  (bundled, better accuracy) — selected by name, not hardcoded.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple, Union

from PIL import Image, ImageOps

ImageOrPath = Union[str, Path, Image.Image]


# --------------------------------------------------------------------------- #
# Tesseract discovery (kept + extended from the original)
# --------------------------------------------------------------------------- #
def _ensure_tesseract_cmd() -> bool:
    import pytesseract

    if shutil.which("tesseract"):
        return True
    candidates: List[Path] = []
    if os.name == "nt":
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
            Path.home() / r"AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
        ]
    else:
        candidates = [
            Path("/opt/homebrew/bin/tesseract"),
            Path("/usr/local/bin/tesseract"),
            Path("/usr/bin/tesseract"),
        ]
    for p in candidates:
        if p.exists():
            pytesseract.pytesseract.tesseract_cmd = str(p)
            return True
    return False


# --------------------------------------------------------------------------- #
# Band preparation
# --------------------------------------------------------------------------- #
def _as_image(image: ImageOrPath) -> Image.Image:
    return image if isinstance(image, Image.Image) else Image.open(image)

def _prep_band(img: Image.Image, band_fraction: float, position: str) -> Image.Image:
    w, h = img.size
    bh = int(h * band_fraction)
    box = (0, h - bh, w, h) if position == "bottom" else (0, 0, w, bh)
    band = img.crop(box)
    # 3x upscale (BILINEAR ~3x faster than LANCZOS, still crisp for OCR),
    # grayscale, autocontrast so white-on-black label text pops.
    band = band.resize((band.width * 3, band.height * 3), Image.Resampling.BILINEAR)
    return ImageOps.autocontrast(band.convert("L"))


def _score(lines: List[str]) -> int:
    """Rough legibility score: count of alphanumeric characters across lines."""
    return sum(ch.isalnum() for line in lines for ch in line)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
def _tesseract_lines(band: Image.Image) -> List[str]:
    import pytesseract

    raw = str(pytesseract.image_to_string(band, config="--psm 6"))
    return [ln.strip() for ln in raw.splitlines() if ln.strip()]


_RAPIDOCR = None  # lazy singleton


def _rapidocr_lines(band: Image.Image) -> List[str]:
    global _RAPIDOCR
    import numpy as np  # type: ignore
    from rapidocr_onnxruntime import RapidOCR  # type: ignore

    if _RAPIDOCR is None:
        _RAPIDOCR = RapidOCR()
    result, _ = _RAPIDOCR(np.array(band.convert("RGB")))
    if not result:
        return []
    return [str(item[1]).strip() for item in result if str(item[1]).strip()]


_BACKENDS = {"tesseract": _tesseract_lines, "rapidocr": _rapidocr_lines}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def read_label(
    image: ImageOrPath,
    backend: str = "tesseract",
    band_fraction: float = 0.15,
) -> Tuple[List[str], str]:
    """Return (lines, position) for the most legible label band.

    `position` is 'bottom' or 'top' — whichever read better. Never raises; on a
    missing/failed OCR engine returns ([], 'bottom').
    """
    reader = _BACKENDS.get(backend)
    if reader is None:
        raise ValueError(f"unknown OCR backend '{backend}'. Known: {', '.join(_BACKENDS)}")
    if backend == "tesseract" and not _ensure_tesseract_cmd():
        return [], "bottom"

    try:
        img = _as_image(image)
        best_lines: List[str] = []
        best_pos = "bottom"
        best_score = -1
        for position in ("bottom", "top"):
            try:
                band = _prep_band(img, band_fraction, position)
                lines = reader(band)
            except Exception:
                lines = []
            s = _score(lines)
            if s > best_score:
                best_lines, best_pos, best_score = lines, position, s
        return best_lines, best_pos
    except Exception as exc:  # noqa: BLE001
        print(f"[OCR] failed for {image!r}: {exc}")
        return [], "bottom"


def ocr_lines(image_path: ImageOrPath, band_fraction: float = 0.15) -> List[str]:
    """Backward-compatible helper matching the original signature."""
    lines, _ = read_label(image_path, band_fraction=band_fraction)
    return lines


def available_backends() -> List[str]:
    out = []
    if _ensure_tesseract_cmd():
        out.append("tesseract")
    try:
        import rapidocr_onnxruntime  # type: ignore  # noqa: F401
        out.append("rapidocr")
    except ImportError:
        pass
    return out
