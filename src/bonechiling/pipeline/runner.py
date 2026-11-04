"""runner.py — headless batch ingestion orchestration.

Replaces the old pipeline.py glue AND the analysis half of the Qt worker.py,
with no Qt/UI dependency so it can be driven by a CLI, the FastAPI server, or a
test. The vision engine is INJECTED (a VisionEngine), so the whole pipeline is
testable with a fake engine and no network.

Per-image flow:
  sha256 -> (skip if already in DB) -> prefilter -> detect+straighten film ->
  OCR best-of(raw photo, film crop) -> normalize -> VLM analyze(film crop) ->
  cross-check OCR vs VLM label -> maybe escalate to cloud -> save.

Patient identity is the folder (see data/db.get_or_create_patient_for_folder).
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..core import film as film_mod
from ..core import ocr as ocr_mod
from ..core.crosscheck import cross_check, has_conflicts
from ..core.normalize import normalize
from ..core.prefilter import PrefilterVerdict, classify
from ..core.schema import XrayFacts
from ..data import db as db_mod
from ..engines.base import EngineResult, VisionEngine

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".dcm", ".dicom"}
ProgressFn = Callable[["ProgressEvent"], None]


@dataclass
class ProgressEvent:
    kind: str                      # folder_start|image_done|image_skipped|folder_done|batch_done
    folder: Optional[str] = None
    file: Optional[str] = None
    done: int = 0
    total: int = 0
    message: str = ""
    extra: Dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Discovery (ported from worker.discover_patient_folders)
# --------------------------------------------------------------------------- #
def discover_patient_folders(paths) -> List[Path]:
    if isinstance(paths, (str, Path)):
        paths = [paths]
    found: List[Path] = []
    seen = set()

    def has_images(d: Path) -> bool:
        return any(
            f.suffix.lower() in IMAGE_EXTS
            for f in d.iterdir()
            if f.is_file() and not f.name.startswith(".")
        )

    def add(d: Path):
        d = d.resolve()
        if d not in seen and d.is_dir() and not d.name.startswith(".") and has_images(d):
            seen.add(d)
            found.append(d)

    for item in paths:
        p = Path(item).resolve()
        if not p.exists():
            continue
        if p.is_file():
            if p.suffix.lower() in IMAGE_EXTS:
                add(p.parent)
        else:
            subdirs = [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if subdirs:
                for root, dirs, files in os.walk(str(p)):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
                    if any(Path(f).suffix.lower() in IMAGE_EXTS for f in files if not f.startswith(".")):
                        add(Path(root))
            elif has_images(p):
                add(p)
    return sorted(found, key=lambda x: str(x).lower())


def sha256_file(path: Path, _buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Escalation decision (real signals only — never self-reported confidence)
# --------------------------------------------------------------------------- #
def should_escalate(facts: XrayFacts, crosscheck: Dict, result: EngineResult) -> bool:
    if result.error:
        return True
    if any("validation" in lim or "non-JSON" in lim for lim in facts.limitations):
        return True
    if has_conflicts(crosscheck):
        return True
    return False


# --------------------------------------------------------------------------- #
# Single image
# --------------------------------------------------------------------------- #
def analyze_image(
    image_path: Path,
    engine: VisionEngine,
    ocr_backend: str = "tesseract",
    escalation_engine: Optional[VisionEngine] = None,
) -> Dict:
    """Run the full per-image analysis. Returns a record dict for db.save_analysis.
    Never raises — failures are captured in the record's `error`/limitations."""
    rec: Dict = {
        "file_path": str(image_path.resolve()),
        "file_sha256": sha256_file(image_path),
        "film_found": False,
        "raw_ocr": [],
    }

    # 1. Film detection + straighten (safe fallback to whole image).
    try:
        det = film_mod.extract_film(image_path)
        film_img, rec["film_found"] = det.image, det.found
    except Exception:
        film_img = None

    # 2. OCR: best of raw photo vs film crop.
    def _ocr(src):
        try:
            lines, _ = ocr_mod.read_label(src, backend=ocr_backend)
            return lines
        except Exception:
            return []

    raw_lines = _ocr(image_path)
    crop_lines = _ocr(film_img) if (film_img is not None and rec["film_found"]) else []
    best_lines = crop_lines if _alnum(crop_lines) > _alnum(raw_lines) else raw_lines
    rec["raw_ocr"] = best_lines
    norm = normalize(best_lines)
    rec["study_date"] = norm.get("study_date")

    # 3. Vision engine on the film crop (fallback: whole image path).
    target = film_img if (film_img is not None and rec["film_found"]) else image_path
    result = engine.analyze(target)

    # 4. Cross-check OCR demographics vs the VLM's label reading.
    crosscheck = cross_check(norm, result.facts.label)

    # 5. Escalate to cloud on real signals (validation fail / conflict / error).
    escalated = False
    if escalation_engine is not None and should_escalate(result.facts, crosscheck, result):
        alt = escalation_engine.analyze(target)
        if alt.ok:
            result = alt
            crosscheck = cross_check(norm, result.facts.label)
            escalated = True

    rec.update(
        facts=result.facts,
        crosscheck={k: _agree_dict(v) for k, v in crosscheck.items()},
        engine=result.engine + ("+escalated" if escalated else ""),
        model_name=result.engine.split(":", 1)[-1],
        latency_ms=result.latency_ms,
        error=result.error,
        raw_response=result.raw_response,
        norm=norm,
    )
    return rec


def _alnum(lines: List[str]) -> int:
    return sum(ch.isalnum() for ln in lines for ch in ln)


def _agree_dict(a) -> Dict:
    return {"ocr": a.ocr, "vlm": a.vlm, "status": a.status, "value": a.value}


# --------------------------------------------------------------------------- #
# Folder / batch
# --------------------------------------------------------------------------- #
def process_folder(
    conn,
    folder: Path,
    engine: VisionEngine,
    escalation_engine: Optional[VisionEngine] = None,
    ocr_backend: str = "tesseract",
    concurrency: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
) -> int:
    """Process one patient folder. Returns the count of newly saved images."""
    folder = Path(folder)
    imgs = sorted(
        f for f in folder.iterdir()
        if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in IMAGE_EXTS
    )
    _emit(progress, ProgressEvent("folder_start", folder=folder.name, total=len(imgs),
                                  message=f"Analyzing {folder.name} ({len(imgs)} files)"))

    patient_id = db_mod.get_or_create_patient_for_folder(conn, str(folder.resolve()), folder.name)

    # Pre-filter + idempotency screening before spending model time.
    todo: List[Path] = []
    for img in imgs:
        if classify(img) == PrefilterVerdict.NON_XRAY:
            _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                          message="skipped: confident non-X-ray"))
            continue
        if db_mod.image_exists(conn, sha256_file(img)):
            _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                          message="skipped: already ingested"))
            continue
        todo.append(img)

    # Cloud engines parallelize across images; local stays serial.
    if concurrency is None:
        concurrency = 1 if getattr(engine, "config", None) and engine.config.is_local else 4

    def _work(img: Path) -> Dict:
        return analyze_image(img, engine, ocr_backend, escalation_engine)

    records: List[Dict] = []
    if concurrency and concurrency > 1 and len(todo) > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            records = list(pool.map(_work, todo))
    else:
        records = [_work(img) for img in todo]

    saved = 0
    best_demographics: Dict = {}
    for img, rec in zip(todo, records):
        # The VLM's image_type is the final authority on whether to keep it.
        if rec["facts"].image_type == "Non-X-ray":
            _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                          message="skipped: VLM says non-X-ray"))
            continue
        if db_mod.save_analysis(conn, patient_id, rec) is not None:
            saved += 1
            _collect_demographics(best_demographics, rec)
        _emit(progress, ProgressEvent("image_done", folder=folder.name, file=img.name,
                                      message=rec["facts"].impression or "analyzed",
                                      extra={"engine": rec["engine"]}))

    if best_demographics:
        db_mod.update_patient_demographics(conn, patient_id, **best_demographics)
    _emit(progress, ProgressEvent("folder_done", folder=folder.name, done=saved, total=len(imgs),
                                  message=f"{folder.name}: {saved} films saved"))
    return saved


def process_batch(
    paths,
    engine: VisionEngine,
    db_path: Optional[Path] = None,
    escalation_engine: Optional[VisionEngine] = None,
    ocr_backend: str = "tesseract",
    concurrency: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
    conn=None,
) -> Dict:
    """Discover patient folders under `paths` and ingest them all."""
    own_conn = conn is None
    conn = conn or db_mod.connect(db_path)
    folders = discover_patient_folders(paths)
    total_saved = 0
    try:
        for i, folder in enumerate(folders, 1):
            total_saved += process_folder(
                conn, folder, engine, escalation_engine, ocr_backend, concurrency, progress
            )
        _emit(progress, ProgressEvent("batch_done", done=total_saved, total=len(folders),
                                      message=f"Done: {len(folders)} folders, {total_saved} films"))
    finally:
        if own_conn:
            conn.close()
    return {"folders": len(folders), "saved": total_saved}


# --------------------------------------------------------------------------- #
def _collect_demographics(acc: Dict, rec: Dict) -> None:
    """Keep the best (verified > single-source) demographics seen for a folder."""
    cc = rec.get("crosscheck", {})
    for field_name in ("name", "age", "sex"):
        cur = cc.get(field_name, {})
        val, status = cur.get("value"), cur.get("status")
        if not val:
            continue
        # verified beats anything already set; otherwise fill only if empty.
        if status == "verified" or field_name not in acc:
            acc[field_name] = val
    if "name" in acc:
        acc["display_name"] = acc["name"]


def _emit(progress: Optional[ProgressFn], event: ProgressEvent) -> None:
    if progress:
        try:
            progress(event)
        except Exception:
            pass
