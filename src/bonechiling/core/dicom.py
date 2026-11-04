"""dicom.py — read DICOM radiographs: render pixels + read demographics tags.

The old code listed .dcm in IMAGE_EXTS and depended on pydicom, but all the
image handling went through PIL, which can't open DICOM — so DICOM silently
failed. This renders the pixel data to a viewable 8-bit image (VOI LUT +
MONOCHROME1 inversion) and reads demographics straight from the tags, which is
far more reliable than OCR when the tags are present.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import numpy as np
from PIL import Image

DICOM_EXTS = {".dcm", ".dicom"}


def is_dicom(path: Union[str, Path]) -> bool:
    """Suffix check, then the 'DICM' magic at byte 128 for extension-less files."""
    p = Path(path)
    if p.suffix.lower() in DICOM_EXTS:
        return True
    try:
        with open(p, "rb") as f:
            f.seek(128)
            return f.read(4) == b"DICM"
    except OSError:
        return False


def _to_image(ds) -> Image.Image:
    """Render a DICOM dataset to an 8-bit grayscale PIL image."""
    arr = ds.pixel_array.astype(np.float32)
    try:
        from pydicom.pixel_data_handlers.util import apply_voi_lut
        arr = apply_voi_lut(ds.pixel_array, ds).astype(np.float32)
    except Exception:
        pass  # fall back to the raw pixel array

    # MONOCHROME1: low values are white -> invert so bone reads normally.
    if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        arr = arr.max() - arr

    lo, hi = float(arr.min()), float(arr.max())
    if hi > lo:
        arr = (arr - lo) / (hi - lo) * 255.0
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), mode="L")


def _parse_age(raw: Any) -> Optional[str]:
    if not raw:
        return None
    m = re.search(r"\d+", str(raw))
    return str(int(m.group())) if m else None


def _tags_to_norm(ds) -> Dict[str, Any]:
    """Demographics in the same shape as core.normalize output (tags-first)."""
    def g(attr):
        v = getattr(ds, attr, None)
        return str(v).strip() if v not in (None, "") else None

    sex = g("PatientSex")
    date = g("StudyDate")  # DICOM DA = YYYYMMDD
    study_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date and len(date) == 8 else None
    view = g("ViewPosition")
    return {
        "name": g("PatientName"),
        "age": _parse_age(getattr(ds, "PatientAge", None)),
        "sex": ("M" if sex and sex.upper().startswith("M") else "F" if sex and sex.upper().startswith("F") else None),
        "patient_id": g("PatientID"),
        "accession_or_id": g("PatientID"),
        "hospital": g("InstitutionName"),
        "body_part": (g("BodyPartExamined") or "").lower() or None,
        "study_date": study_date,
        "views": [view.upper()] if view else [],
        "warnings": [],
        "fields": {},
    }


class DicomStudy:
    def __init__(self, image: Image.Image, norm: Dict[str, Any]):
        self.image = image
        self.norm = norm


def read_dicom(path: Union[str, Path]) -> Optional[DicomStudy]:
    """Return a DicomStudy (rendered image + tag demographics), or None on failure."""
    try:
        import pydicom

        ds = pydicom.dcmread(str(path), force=True)
        if "PixelData" not in ds:
            return None
        return DicomStudy(_to_image(ds), _tags_to_norm(ds))
    except Exception:
        return None
