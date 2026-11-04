"""schema.py — the typed contract every vision engine must satisfy.

A single Pydantic model (`XrayFacts`) defines the JSON shape we ask every
provider (local Ollama or a cloud API) to return. Engines validate/repair their
raw response against this, so the rest of the pipeline never touches free-form
model text. Objective-facts-only: no diagnoses, no speculation.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Sub-models
# --------------------------------------------------------------------------- #
class HardwareItem(BaseModel):
    """One orthopedic implant / construct visible on the film."""

    implant: str = Field(default="", description="e.g. 'plate', 'cortical screw', 'K-wire', 'IM nail'")
    location: str = Field(default="", description="anatomical location, e.g. 'distal radius'")
    count: int = Field(default=1, ge=0)
    integrity: str = Field(default="intact", description="'intact' or an observed issue (loose/displaced/broken)")

    @field_validator("count", mode="before")
    @classmethod
    def _coerce_count(cls, v: Any) -> int:
        if v is None or v == "":
            return 1
        if isinstance(v, str):
            m = re.search(r"\d+", v)
            return int(m.group()) if m else 1
        try:
            return int(v)
        except (TypeError, ValueError):
            return 1

    @field_validator("implant", "location", "integrity", mode="before")
    @classmethod
    def _coerce_str(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()


class LabelReading(BaseModel):
    """Demographics the VLM read off the printed film label.

    Kept separate from OCR so the pipeline can cross-check the two sources
    (agreement => verified, disagreement => flag for the doctor). This replaces
    the model's uncalibrated self-reported confidence as a routing signal.
    """

    name: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    patient_id: Optional[str] = None
    study_date: Optional[str] = None
    hospital: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        if v is None:
            return None
        s = str(v).strip()
        return s or None


# --------------------------------------------------------------------------- #
# Top-level contract
# --------------------------------------------------------------------------- #
class XrayFacts(BaseModel):
    """Objective radiographic facts for one image. The engine JSON contract."""

    image_type: str = Field(default="Unknown", description="'X-ray', 'Non-X-ray', or 'Unknown'")
    body_part: Optional[str] = None
    laterality: Optional[str] = Field(default=None, description="left / right / bilateral / None")
    views: List[str] = Field(default_factory=list, description="projections, e.g. ['AP', 'LAT']")
    hardware: List[HardwareItem] = Field(default_factory=list)
    visible_findings: List[str] = Field(default_factory=list, description="strictly observable facts only")
    impression: Optional[str] = Field(default=None, description="factual summary; NOT a diagnosis")
    image_quality: Optional[str] = None
    label: LabelReading = Field(default_factory=LabelReading)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limitations: List[str] = Field(default_factory=list)

    # ----- coercions so a slightly-off model response still validates ----- #
    @field_validator("views", "visible_findings", "limitations", mode="before")
    @classmethod
    def _as_str_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        out = []
        for item in v:
            if item is None:
                continue
            s = str(item).strip()
            if s and s.lower() not in ("none", "null", "n/a", "[]"):
                out.append(s)
        return out

    @field_validator("hardware", mode="before")
    @classmethod
    def _normalize_hardware(cls, v: Any) -> List[Any]:
        """Accept a list of dicts OR a list of free-text strings like
        '1 Olecranon plate with 4 cortical screws (intact)'."""
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        items: List[Any] = []
        for raw in v:
            if isinstance(raw, dict):
                items.append(raw)
            elif raw is not None:
                parsed = _parse_hardware_string(str(raw))
                if parsed:
                    items.append(parsed)
        return items

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_conf(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))

    @field_validator("image_type", mode="before")
    @classmethod
    def _norm_type(cls, v: Any) -> str:
        if not v:
            return "Unknown"
        s = str(v).strip().lower()
        if "non" in s and "ray" in s:
            return "Non-X-ray"
        if "ray" in s or "radiograph" in s:
            return "X-ray"
        return str(v).strip() or "Unknown"

    @property
    def is_xray(self) -> bool:
        return self.image_type == "X-ray" and bool(self.body_part)

    @classmethod
    def json_schema_hint(cls) -> str:
        """Compact schema description injected into prompts for weak models."""
        return json.dumps(
            {
                "image_type": "X-ray | Non-X-ray",
                "body_part": "string | null",
                "laterality": "left | right | bilateral | null",
                "views": ["AP", "LAT", "..."],
                "hardware": [{"implant": "string", "location": "string", "count": 1, "integrity": "intact"}],
                "visible_findings": ["string"],
                "impression": "string | null",
                "image_quality": "string | null",
                "label": {
                    "name": "string | null", "age": "string | null", "sex": "M | F | null",
                    "patient_id": "string | null", "study_date": "string | null", "hospital": "string | null",
                },
                "confidence": 0.0,
                "limitations": ["string"],
            },
            indent=0,
        )


def _parse_hardware_string(s: str) -> Optional[dict]:
    """Turn 'Olecranon plate with 4 cortical screws (intact)' into a dict.

    Deliberately lightweight: the richer cross-projection reconciliation still
    lives in core/reconcile.py. Returns None for empty/no-hardware strings.
    """
    s = s.strip()
    if not s or s.lower() in ("none", "null", "n/a", "[]", "no hardware", "none identified"):
        return None

    integrity = "intact"
    m_int = re.search(r"\(([^)]+)\)", s)
    if m_int:
        txt = m_int.group(1).lower()
        if any(w in txt for w in ("loose", "displace", "break", "broke", "fractur", "fail")):
            integrity = txt.strip()
        s = (s[: m_int.start()] + s[m_int.end():]).strip()

    m_cnt = re.match(r"\s*(\d+)\s+(.*)", s)
    if m_cnt:
        count = int(m_cnt.group(1))
        remainder = m_cnt.group(2).strip()
    else:
        count = 1
        remainder = s

    return {"implant": remainder, "location": "", "count": count, "integrity": integrity}


def repair_and_validate(raw: Any) -> XrayFacts:
    """Best-effort parse of a model response into XrayFacts.

    Accepts a dict, a JSON string, or a string with JSON embedded in prose
    (common with small models). Never raises: on total failure returns an
    empty XrayFacts with a limitation note, so the pipeline keeps moving.
    """
    data: Any = raw
    if isinstance(raw, str):
        data = _extract_json_blob(raw)
    if not isinstance(data, dict):
        return XrayFacts(
            image_type="Unknown",
            limitations=["engine returned non-JSON output"],
            impression=(str(raw)[:400] if raw else None),
        )
    try:
        return XrayFacts.model_validate(data)
    except Exception as exc:  # noqa: BLE001 — want the pipeline to survive any schema drift
        return XrayFacts(
            image_type=str(data.get("image_type") or "Unknown"),
            body_part=data.get("body_part"),
            impression=data.get("impression"),
            limitations=[f"schema validation failed: {type(exc).__name__}"],
        )


def _extract_json_blob(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Strip ```json fences, then grab the outermost {...}
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return text
