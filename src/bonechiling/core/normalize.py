"""normalize.py — turn messy OCR label lines into typed demographic fields.

Generalized from the original single-hospital regex:
- Each field is a `Field(value, confidence, source)` so the pipeline can
  cross-check OCR against the VLM's label reading (agreement => verified).
- Multiple date layouts (DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YYYY, ...) instead of
  assuming DD/MM/YYYY.
- Extensible pattern lists for body part / views / person line.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Original real OCR output, frozen as a regression test forever.
SAMPLE_LINES = [
    "Elbow AP/LAT 02/01/2026 10:28:41 AM Elbow AP/LAT 02/01/2026 10:29:32 AM",
    "H.J. DOSHI SARVAJANIK HOSPITAL, RAJKOT.",
    "KARSHANBHAI BHARVAD 35 year(s) / Male 020110",
]


@dataclass
class Field:
    value: Optional[Any] = None
    confidence: float = 0.0
    source: str = "ocr"

    def as_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "confidence": round(self.confidence, 2), "source": self.source}


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #
VIEW_RE = re.compile(r"\b(AP|PA|LAT|LATERAL|OBLIQUE|MORTISE|AXIAL|SKYLINE)\b", re.I)
BODY_PARTS = [
    "elbow", "chest", "wrist", "knee", "shoulder", "ankle", "hand", "foot",
    "hip", "pelvis", "spine", "skull", "forearm", "humerus", "femur", "tibia",
    "fibula", "clavicle", "radius", "ulna", "calcaneus", "scaphoid", "patella",
    "lumbar", "cervical", "thoracic", "mandible", "sacrum", "scapula", "rib",
]
# common OCR mis-spellings -> canonical
BODY_FIX = {"femer": "femur", "tibla": "tibia", "ankie": "ankle", "cheast": "chest"}
BODY_RE = re.compile(r"\b(" + "|".join(list(BODY_PARTS) + list(BODY_FIX)) + r")\b", re.I)

PERSON_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z .'-]{2,})\s+(?P<age>\d{1,3})\s*(?:years?|yrs?|y)?\s*"
    r"(?:\(s\))?\s*[/\-,]?\s*(?P<sex>male|female|m|f)\b"
    r"(?:\s+(?P<rest>[A-Za-z0-9]+))?",
    re.I,
)

# Date layouts we recognize, each with the strptime format to parse it.
DATE_PATTERNS = [
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), "%Y-%m-%d", "YYYY-MM-DD"),
    (re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"), "%d/%m/%Y", "DD/MM/YYYY"),
    (re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b"), "%d-%m-%Y", "DD-MM-YYYY"),
    (re.compile(r"\b(\d{1,2}[ -][A-Za-z]{3,9}[ -]\d{4})\b"), "%d-%b-%Y", "DD-Mon-YYYY"),
]
ID_RE = re.compile(r"\b(\d{4,})\b")


def _parse_date(text: str) -> Field:
    for rx, fmt, label in DATE_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        raw = m.group(1).replace(" ", "-")
        dt = None
        try:
            dt = datetime.strptime(raw, fmt)
        except ValueError:
            # DD/MM vs MM/DD ambiguity: if day-first fails (e.g. month > 12),
            # try month-first by SWAPPING %d and %m (not duplicating them).
            if "%d" in fmt and "%m" in fmt:
                swapped = fmt.replace("%d", "\0").replace("%m", "%d").replace("\0", "%m")
                try:
                    dt = datetime.strptime(raw, swapped)
                except ValueError:
                    dt = None
        if dt is None:
            return Field(None, 0.0)
        ambiguous = label in ("DD/MM/YYYY", "DD-MM-YYYY") and dt.day <= 12
        conf = 0.7 if ambiguous else 0.9  # could be MM/DD; lower confidence
        return Field(dt.strftime("%Y-%m-%d"), conf)
    return Field(None, 0.0)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def normalize(lines: List[str]) -> Dict[str, Any]:
    """Structured demographics from OCR lines. Backward-compatible top-level
    keys (name/age/sex/...) plus a `fields` map carrying per-field confidence."""
    text = "\n".join(lines)
    fields: Dict[str, Field] = {
        "name": Field(), "age": Field(), "sex": Field(),
        "patient_id": Field(), "hospital": Field(), "body_part": Field(),
        "study_date": Field(),
    }
    warnings: List[str] = []

    # views
    views: List[str] = []
    for v in VIEW_RE.findall(text):
        vu = v.upper()
        vu = "LAT" if vu == "LATERAL" else vu
        if vu not in views:
            views.append(vu)

    # body part
    bm = BODY_RE.search(text)
    if bm:
        bp = bm.group(1).lower()
        fields["body_part"] = Field(BODY_FIX.get(bp, bp), 0.85)

    # hospital
    for line in lines:
        if "hospital" in line.lower() or "clinic" in line.lower():
            fields["hospital"] = Field(line.strip(" |-_.,:;~'"), 0.8)
            break

    # date
    fields["study_date"] = _parse_date(text)
    if fields["study_date"].confidence and fields["study_date"].confidence < 0.8:
        warnings.append("date order ambiguous (assumed day-first)")

    # person line
    for line in lines:
        pm = PERSON_RE.search(line)
        if not pm:
            continue
        name = pm.group("name").strip(" |-_.,:;~'")
        # reject lines that are mostly non-name noise
        if len(name) < 3 or not any(c.isalpha() for c in name):
            continue
        fields["name"] = Field(name, 0.8)
        fields["age"] = Field(pm.group("age"), 0.85)
        sex = pm.group("sex").lower()
        fields["sex"] = Field("M" if sex in ("male", "m") else "F", 0.9)
        rest = pm.group("rest")
        if rest and rest.isdigit():
            fields["patient_id"] = Field(rest, 0.6)
            warnings.append("numeric code after person line stored as patient_id (may be accession)")
        break
    else:
        warnings.append("no person line found")

    # fall back: a long bare number anywhere is a candidate ID
    if fields["patient_id"].value is None:
        m = ID_RE.search(text)
        if m:
            fields["patient_id"] = Field(m.group(1), 0.4)

    out: Dict[str, Any] = {k: f.value for k, f in fields.items()}
    out["views"] = views
    out["warnings"] = warnings
    out["fields"] = {k: f.as_dict() for k, f in fields.items()}
    # backward-compat alias used by the old pipeline
    out["accession_or_id"] = fields["patient_id"].value
    return out
