"""harness.py — measure extraction accuracy against ground-truth labels.

The old eval_results.json only recorded outputs + timings; it could not tell
you whether an answer was *right*. This runs the real pipeline over labeled
images and reports per-field accuracy + latency per engine, so a model/config
change is proven, not guessed.

Label file (JSON list), each entry:
  {
    "file": "test/1/20251018_130343.jpg",   # path relative to images_root
    "image_type": "X-ray",                   # or "Non-X-ray"
    "name": "CHANDANBEN RATHOD",             # expected patient name (optional)
    "body_part": "femur",                     # optional
    "views": ["AP", "LAT"],                   # optional
    "hardware_present": false                  # optional bool
  }
Any omitted field is simply not scored for that image.

NOTE: because the sample data is real PHI, run this locally / on a private
runner — never in public CI.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..core.crosscheck import _names_match, _norm
from ..core.schema import XrayFacts
from ..engines.base import VisionEngine
from ..pipeline import runner


def load_labels(path) -> List[Dict]:
    data = json.loads(Path(path).read_text())
    if isinstance(data, dict):           # allow {"labels": [...], "note": ...}
        data = data.get("labels", [])
    return data


# --------------------------------------------------------------------------- #
# Scoring (pure functions — unit-testable without a model)
# --------------------------------------------------------------------------- #
def _views_f1(expected: List[str], got: List[str]) -> float:
    e = {str(v).upper().replace("LATERAL", "LAT") for v in expected}
    g = {str(v).upper().replace("LATERAL", "LAT") for v in got}
    if not e and not g:
        return 1.0
    if not e or not g:
        return 0.0
    tp = len(e & g)
    prec = tp / len(g)
    rec = tp / len(e)
    return 0.0 if (prec + rec) == 0 else 2 * prec * rec / (prec + rec)


def score_fields(label: Dict, facts: XrayFacts, final_name: Optional[str]) -> Dict[str, float]:
    """Return {field: score in [0,1]} for only the fields present in `label`."""
    out: Dict[str, float] = {}
    if "image_type" in label:
        want_xray = str(label["image_type"]).lower().startswith("x")
        out["image_type"] = float(facts.is_xray == want_xray)
    if label.get("body_part"):
        exp, got = _norm(label["body_part"]), _norm(facts.body_part)
        out["body_part"] = float(bool(got) and (exp in got or got in exp))
    if "views" in label:
        out["views"] = _views_f1(label["views"], facts.views)
    if label.get("name"):
        out["name"] = float(_names_match(_norm(label["name"]), _norm(final_name)))
    if "hardware_present" in label:
        out["hardware_present"] = float(bool(facts.hardware) == bool(label["hardware_present"]))
    return out


# --------------------------------------------------------------------------- #
# Evaluation run
# --------------------------------------------------------------------------- #
@dataclass
class EvalReport:
    engine: str
    n_images: int
    field_accuracy: Dict[str, float]
    mean_latency_ms: float
    errors: int
    per_image: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "engine": self.engine,
            "n_images": self.n_images,
            "field_accuracy": {k: round(v, 3) for k, v in self.field_accuracy.items()},
            "overall_accuracy": round(
                statistics.mean(self.field_accuracy.values()), 3) if self.field_accuracy else None,
            "mean_latency_ms": round(self.mean_latency_ms, 1),
            "errors": self.errors,
            "per_image": self.per_image,
        }


def evaluate(
    engine: VisionEngine,
    labels: List[Dict],
    images_root: Path,
    ocr_backend: str = "tesseract",
    escalation_engine: Optional[VisionEngine] = None,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> EvalReport:
    images_root = Path(images_root)
    per_field: Dict[str, List[float]] = {}
    latencies: List[float] = []
    errors = 0
    per_image: List[Dict] = []

    for i, label in enumerate(labels, 1):
        img = images_root / label["file"]
        if not img.exists():
            img = Path(label["file"])  # allow absolute paths in labels
        if progress:
            progress(i, len(labels), img.name)
        rec = runner.analyze_image(img, engine, ocr_backend, escalation_engine)
        facts: XrayFacts = rec["facts"]
        if rec.get("error"):
            errors += 1
        latencies.append(rec.get("latency_ms") or 0)
        final_name = rec.get("crosscheck", {}).get("name", {}).get("value")
        scores = score_fields(label, facts, final_name)
        for k, v in scores.items():
            per_field.setdefault(k, []).append(v)
        per_image.append({"file": label["file"], "scores": scores, "engine": rec["engine"]})

    field_acc = {k: statistics.mean(v) for k, v in per_field.items()}
    return EvalReport(
        engine=getattr(engine, "config", None) and f"{engine.config.provider}:{engine.config.model}" or "engine",
        n_images=len(labels),
        field_accuracy=field_acc,
        mean_latency_ms=statistics.mean(latencies) if latencies else 0.0,
        errors=errors,
        per_image=per_image,
    )


def print_report(report: EvalReport) -> None:
    d = report.to_dict()
    print(f"\n=== Eval: {d['engine']} ===")
    print(f"images: {d['n_images']}   errors: {d['errors']}   "
          f"mean latency: {d['mean_latency_ms']} ms")
    for fieldname, acc in d["field_accuracy"].items():
        print(f"  {fieldname:16s} {acc*100:5.1f}%")
    if d["overall_accuracy"] is not None:
        print(f"  {'OVERALL':16s} {d['overall_accuracy']*100:5.1f}%")
