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

from ..core import dicom as dicom_mod
from ..core import film as film_mod
from ..core import ocr as ocr_mod
from ..core.crosscheck import cross_check, has_conflicts
from ..core.normalize import normalize
from ..core.prefilter import PrefilterVerdict, classify
from ..core.schema import XrayFacts
from ..data import db as db_mod
from ..engines.base import EngineResult, VisionEngine

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".dcm", ".dicom", ".tif", ".tiff", ".bmp", ".webp"}
StopFn = Callable[[], bool]


def is_candidate(f: Path) -> bool:
    """An image we can read: known extension, or an extension-less DICOM
    (scanners often write files like ``IM0001`` with no suffix)."""
    if not f.is_file() or f.name.startswith(".") or f.name.lower() in ("thumbs.db", "desktop.ini"):
        return False
    if f.suffix.lower() in IMAGE_EXTS:
        return True
    return f.suffix == "" and dicom_mod.is_dicom(f)


def clean_path(raw: str) -> str:
    """Undo common copy-paste damage: surrounding quotes (Windows "Copy as
    path"), whitespace, and file:// URLs."""
    p = (raw or "").strip().strip('"').strip("'").strip()
    if p.lower().startswith("file://"):
        from urllib.parse import unquote, urlparse
        u = urlparse(p)
        p = unquote(u.path)
        if len(p) > 2 and p[0] == "/" and p[2] == ":":   # /C:/x -> C:/x
            p = p[1:]
    return p
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
        try:
            return any(is_candidate(f) for f in d.iterdir())
        except OSError:
            return False

    def add(d: Path):
        d = d.resolve()
        if d not in seen and d.is_dir() and not d.name.startswith(".") and has_images(d):
            seen.add(d)
            found.append(d)

    for item in paths:
        p = Path(clean_path(str(item))).resolve()
        if not p.exists():
            continue
        if p.is_file():
            if is_candidate(p):
                add(p.parent)
        else:
            try:
                subdirs = [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]
            except OSError:
                continue
            if subdirs:
                for root, dirs, files in os.walk(str(p)):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
                    if any(is_candidate(Path(root) / f) for f in files):
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
    precomputed_sha: Optional[str] = None,
) -> Dict:
    """Run the full per-image analysis. Returns a record dict for db.save_analysis.
    Never raises — failures are captured in the record's `error`/limitations.
    `precomputed_sha` avoids re-hashing a file already hashed for dedup."""
    rec: Dict = {
        "file_path": str(image_path.resolve()),
        "file_sha256": precomputed_sha or sha256_file(image_path),
        "film_found": False,
        "raw_ocr": [],
        "source": "photo",
    }
    norm = None
    target = image_path

    # 0. DICOM: render pixels + read demographics from tags (no OCR/film needed).
    if dicom_mod.is_dicom(image_path):
        study = dicom_mod.read_dicom(image_path)
        if study is not None:
            target = study.image
            norm = study.norm
            rec["source"] = "dicom"

    # 1-2. Photo path: detect/straighten film, then OCR best-of(raw, crop).
    if norm is None:
        try:
            det = film_mod.extract_film(image_path)
            film_img, rec["film_found"] = det.image, det.found
        except Exception:
            film_img = None

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
        target = film_img if (film_img is not None and rec["film_found"]) else image_path

    rec["study_date"] = norm.get("study_date")

    # 3. Vision engine on the chosen image (film crop, DICOM render, or raw).
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
    should_stop: Optional[StopFn] = None,
) -> int:
    """Process one patient folder. Returns the count of newly saved images.

    Each film is saved as soon as it is analyzed, so quitting mid-folder keeps
    the work done so far. Films whose earlier attempt failed are retried; films
    analyzed successfully before are skipped.
    """
    stop = should_stop or (lambda: False)
    folder = Path(folder)
    imgs = sorted((f for f in folder.iterdir() if is_candidate(f)), key=lambda f: f.name.lower())
    _emit(progress, ProgressEvent("folder_start", folder=folder.name, total=len(imgs),
                                  message=f"Analyzing {folder.name} ({len(imgs)} files)"))

    folder_key = str(folder.resolve())
    existed = conn.execute("SELECT id FROM patients WHERE folder_path = ?", (folder_key,)).fetchone()
    patient_id = db_mod.get_or_create_patient_for_folder(conn, folder_key, folder.name)

    # Screening before spending model time. Hash once and reuse it later.
    todo: List[tuple] = []  # (path, sha)
    seen_sha = set()
    skipped = failed = 0
    for img in imgs:
        if stop():
            break
        try:
            sha = sha256_file(img)
            if sha in seen_sha:
                skipped += 1
                _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                              message="skipped: identical copy of another file in this folder"))
                continue
            prev = db_mod.image_by_sha(conn, sha)
            if prev and prev.get("error"):
                db_mod.delete_images(conn, [prev["id"]])      # last attempt failed: retry it
                _emit(progress, ProgressEvent("image_retry", folder=folder.name, file=img.name,
                                              message="retrying: previous attempt failed"))
            elif prev:
                skipped += 1
                where = "" if prev["patient_id"] == patient_id else \
                    f" under {Path(prev.get('folder_path') or '?').name}"
                _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                              message=f"skipped: already analyzed{where}"))
                continue
            # DICOM is never a "non-X-ray"; only screen photos with the heuristic.
            if not dicom_mod.is_dicom(img) and classify(img) == PrefilterVerdict.NON_XRAY:
                skipped += 1
                _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                              message="skipped: not an X-ray (photo check)"))
                continue
        except OSError as exc:
            failed += 1
            _emit(progress, ProgressEvent("error", folder=folder.name, file=img.name,
                                          message=f"{img.name}: can't read file ({exc.strerror or exc})"))
            continue
        seen_sha.add(sha)
        todo.append((img, sha))

    # Cloud engines parallelize across images; local stays serial.
    if concurrency is None:
        concurrency = 1 if getattr(engine, "config", None) and engine.config.is_local else 4

    def _work(item: tuple) -> Optional[Dict]:
        if stop():
            return None
        img, sha = item
        try:
            return analyze_image(img, engine, ocr_backend, escalation_engine, precomputed_sha=sha)
        except Exception as exc:  # noqa: BLE001 - one bad file must not end the batch
            return {"_crash": f"{type(exc).__name__}: {exc}"}

    saved = 0
    pool = ThreadPoolExecutor(max_workers=concurrency) if concurrency and concurrency > 1 and len(todo) > 1 else None
    try:
        results = pool.map(_work, todo) if pool else (_work(t) for t in todo)
        for (img, _sha), rec in zip(todo, results):   # results arrive in order; save each at once
            if rec is None:          # cancelled
                continue
            if "_crash" in rec:
                failed += 1
                _emit(progress, ProgressEvent("image_failed", folder=folder.name, file=img.name,
                                              message=f"failed: {rec['_crash']}"))
                continue
            # The VLM's image_type is the final authority on whether to keep it.
            if rec["facts"].image_type == "Non-X-ray" and not rec.get("error"):
                skipped += 1
                _emit(progress, ProgressEvent("image_skipped", folder=folder.name, file=img.name,
                                              message="skipped: model says this is not an X-ray"))
                continue
            # The same file path with new content replaces the old result.
            old = [i for i in db_mod.image_ids_for_path(conn, patient_id, rec["file_path"])]
            if db_mod.save_analysis(conn, patient_id, rec) is not None:
                if old:
                    db_mod.delete_images(conn, old)
                if rec.get("error"):
                    failed += 1
                    _emit(progress, ProgressEvent("image_failed", folder=folder.name, file=img.name,
                                                  message=f"failed: {rec['error']}"))
                else:
                    saved += 1
                    _emit(progress, ProgressEvent("image_done", folder=folder.name, file=img.name,
                                                  message=rec["facts"].impression or "analyzed",
                                                  extra={"engine": rec["engine"]}))
    finally:
        if pool:
            pool.shutdown(wait=True, cancel_futures=True)

    refresh_patient_demographics(conn, patient_id)
    # Don't leave an empty patient behind for a folder that yielded nothing.
    if not existed and db_mod.patient_image_count(conn, patient_id) == 0:
        db_mod.delete_patient(conn, patient_id)

    parts = [f"{saved} saved"] + ([f"{failed} failed"] if failed else []) + ([f"{skipped} skipped"] if skipped else [])
    _emit(progress, ProgressEvent("folder_done", folder=folder.name, done=saved, total=len(imgs),
                                  message=f"{folder.name}: " + ", ".join(parts),
                                  extra={"failed": failed, "skipped": skipped}))
    return saved


def refresh_patient_demographics(conn, patient_id: int) -> None:
    """Recompute name/age/sex from every film stored for the patient, so
    re-reading or removing one film can't replace a good name with a worse one."""
    import json as _json
    acc: Dict = {}
    for img in db_mod.get_patient_images(conn, patient_id):
        if img.get("error"):
            continue
        try:
            cc = _json.loads(img.get("crosscheck_json") or "{}")
        except ValueError:
            cc = {}
        _collect_demographics(acc, {"crosscheck": cc})
    if acc:
        db_mod.update_patient_demographics(conn, patient_id, **acc)


def process_batch(
    paths,
    engine: VisionEngine,
    db_path: Optional[Path] = None,
    escalation_engine: Optional[VisionEngine] = None,
    ocr_backend: str = "tesseract",
    concurrency: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
    conn=None,
    should_stop: Optional[StopFn] = None,
) -> Dict:
    """Discover patient folders under `paths` and ingest them all.

    Problems with individual paths or folders are reported as `error` events
    and the rest of the batch carries on.
    """
    stop = should_stop or (lambda: False)
    if isinstance(paths, (str, Path)):
        paths = [paths]
    cleaned = [clean_path(str(p)) for p in paths if clean_path(str(p))]
    for raw in cleaned:
        p = Path(raw)
        if not p.exists():
            _emit(progress, ProgressEvent("error", message=f"Not found on this PC: {raw}"))
        elif not discover_patient_folders([raw]):
            _emit(progress, ProgressEvent("error", message=f"No X-ray images found in: {raw}"))

    own_conn = conn is None
    conn = conn or db_mod.connect(db_path)
    folders = discover_patient_folders(cleaned)
    total_saved = 0
    done_folders = 0
    try:
        for folder in folders:
            if stop():
                break
            try:
                total_saved += process_folder(
                    conn, folder, engine, escalation_engine, ocr_backend, concurrency, progress, stop
                )
            except Exception as exc:  # noqa: BLE001 - keep going with the next folder
                _emit(progress, ProgressEvent("error", folder=folder.name,
                                              message=f"{folder.name}: stopped with an error ({exc})"))
                _emit(progress, ProgressEvent("folder_done", folder=folder.name, done=0,
                                              message=f"{folder.name}: not completed"))
            done_folders += 1
        _emit(progress, ProgressEvent("batch_done", done=total_saved, total=len(folders),
                                      message=f"Done: {done_folders} of {len(folders)} folders, {total_saved} films"))
    finally:
        if own_conn:
            conn.close()
    return {"folders": len(folders), "saved": total_saved, "cancelled": stop()}


# --------------------------------------------------------------------------- #
_RANK = {"verified": 3, "vlm_only": 2, "ocr_only": 1}


def _collect_demographics(acc: Dict, rec: Dict) -> None:
    """Keep the best demographics seen across a folder's films.

    Name: prefer a verified reading, then a longer (more complete) one — so a
    folder where one film reads 'JAYANTIBHAI SOLANKI' and another reads
    'I SOLANKI' keeps the full name, not the truncated OCR miss.
    """
    cc = rec.get("crosscheck", {})
    # name with rank + length preference
    cur = cc.get("name", {})
    val, status = cur.get("value"), cur.get("status")
    if val:
        best = acc.get("_name_rank", (-1, -1))
        cand = (_RANK.get(status, 0), len(str(val)))
        if cand > best:
            acc["name"] = val
            acc["display_name"] = val
            acc["_name_rank"] = cand
    # age / sex: verified wins, else first non-empty
    for field_name in ("age", "sex"):
        c = cc.get(field_name, {})
        v, s = c.get("value"), c.get("status")
        if v and (s == "verified" or field_name not in acc):
            acc[field_name] = v


def _emit(progress: Optional[ProgressFn], event: ProgressEvent) -> None:
    if progress:
        try:
            progress(event)
        except Exception:
            pass
