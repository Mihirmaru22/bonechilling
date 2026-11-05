"""crosscheck.py — reconcile OCR demographics against the VLM's label reading.

Two independent reads of the same printed label: Tesseract/RapidOCR (fast,
weaker on photos) and the vision model (stronger at reading text in a photo).
Agreement => the field is trustworthy ("verified"); disagreement => surface it
to the doctor rather than silently picking one. This replaces the model's
uncalibrated self-reported confidence as the escalation / trust signal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

from .schema import LabelReading


@dataclass
class FieldAgreement:
    field: str
    ocr: Optional[str]
    vlm: Optional[str]
    status: str          # verified | conflict | ocr_only | vlm_only | missing
    value: Optional[str]  # best value to use

    @property
    def verified(self) -> bool:
        return self.status == "verified"


def _norm(s: Optional[str]) -> str:
    if s is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _names_match(a: str, b: str) -> bool:
    """Name match tolerant of OCR noise and token reordering."""
    if not a or not b:
        return False
    if a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / max(len(ta), len(tb))
    return overlap >= 0.6


def _values_match(field: str, a: str, b: str) -> bool:
    if not a or not b:
        return False
    if field == "name":
        return _names_match(a, b)
    if field == "sex":
        return a[0] == b[0]  # M/F/male/female
    return a == b


def _compare_one(field: str, ocr_val: Optional[str], vlm_val: Optional[str]) -> FieldAgreement:
    a, b = _norm(ocr_val), _norm(vlm_val)
    if not a and not b:
        return FieldAgreement(field, ocr_val, vlm_val, "missing", None)
    if a and not b:
        return FieldAgreement(field, ocr_val, vlm_val, "ocr_only", ocr_val)
    if b and not a:
        return FieldAgreement(field, ocr_val, vlm_val, "vlm_only", vlm_val)
    if _values_match(field, a, b):
        # Prefer the richer (longer) spelling when both agree.
        value = ocr_val if len(str(ocr_val)) >= len(str(vlm_val)) else vlm_val
        return FieldAgreement(field, ocr_val, vlm_val, "verified", value)
    return FieldAgreement(field, ocr_val, vlm_val, "conflict", vlm_val)


FIELDS = ("name", "age", "sex", "patient_id", "study_date", "hospital")


def cross_check(ocr_norm: Dict, vlm_label: LabelReading) -> Dict[str, FieldAgreement]:
    """Return a per-field agreement map for the label demographics."""
    ocr_map = {
        "name": ocr_norm.get("name"),
        "age": ocr_norm.get("age"),
        "sex": ocr_norm.get("sex"),
        "patient_id": ocr_norm.get("patient_id") or ocr_norm.get("accession_or_id"),
        "study_date": ocr_norm.get("study_date"),
        "hospital": ocr_norm.get("hospital"),
    }
    vlm_map = {
        "name": vlm_label.name,
        "age": vlm_label.age,
        "sex": vlm_label.sex,
        "patient_id": vlm_label.patient_id,
        "study_date": vlm_label.study_date,
        "hospital": vlm_label.hospital,
    }
    return {f: _compare_one(f, ocr_map[f], vlm_map[f]) for f in FIELDS}


def has_conflicts(agreement: Dict[str, FieldAgreement]) -> bool:
    """True if any demographic field conflicts — a signal to escalate/flag."""
    return any(a.status == "conflict" for a in agreement.values())
