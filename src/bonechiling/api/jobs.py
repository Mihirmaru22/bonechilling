"""jobs.py — background ingestion jobs for the API.

process_batch is blocking (it does OCR + model calls), so the API runs it in a
worker thread and records progress on the job. The FastAPI layer exposes job
status over REST and streams the event log over a WebSocket.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..data import settings as settings_mod
from ..engines.base import VisionEngine
from ..engines.registry import PRESETS, build_engine, config_from_preset
from ..pipeline import runner

# A factory lets tests inject a fake engine instead of a real provider.
EngineFactory = Callable[[Dict], Tuple[VisionEngine, Optional[VisionEngine]]]


def build_engines(config: Dict) -> Tuple[VisionEngine, Optional[VisionEngine]]:
    """Build (primary, escalation) engines from config + keyring-stored keys."""
    def one(provider: Optional[str], model: Optional[str]) -> Optional[VisionEngine]:
        if not provider:
            return None
        preset = PRESETS.get(provider)
        if preset is None:
            raise ValueError(f"unknown provider '{provider}'")
        key = settings_mod.get_api_key(provider) if preset.needs_key else None
        if preset.needs_key and not key:
            raise ValueError(f"provider '{provider}' has no API key stored")
        return build_engine(config_from_preset(provider, model=model, api_key=key))

    primary = one(config.get("provider"), config.get("model"))
    if primary is None:
        raise ValueError("no primary provider configured")
    escalation = one(config.get("escalate_provider"), config.get("escalate_model"))
    return primary, escalation


def preflight(engine: VisionEngine) -> Optional[str]:
    """Catch a dead engine before every film fails one by one.

    Returns a plain-language problem, or None if the engine looks usable."""
    cfg = getattr(engine, "config", None)
    check = getattr(engine, "health_check", None)
    if check is None:
        return None
    try:
        ok, detail = check()
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, str(exc)
    if not ok:
        if cfg is not None and cfg.is_local:
            return ("Can't reach Ollama on this PC. Start Ollama (or open Settings → Local AI) "
                    f"and try again. ({detail})")
        return f"The AI provider rejected the connection: {detail}. Check the API key in Settings."
    if cfg is not None and cfg.is_local:
        from . import ollama_helper
        installed = ollama_helper.status().get("models", [])
        want = cfg.model if ":" in cfg.model else cfg.model + ":latest"
        if installed and want not in installed and cfg.model not in installed:
            return (f"The model '{cfg.model}' isn't downloaded in Ollama yet. "
                    "Download it in Settings, or pick an installed model.")
    return None


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        # One ingest at a time: parallel jobs would race on the same films and
        # compete for the local model. Later jobs wait their turn ("queued").
        self._run_lock = threading.Lock()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            j = self._jobs.get(job_id)
            if not j or j["status"] in ("completed", "failed", "cancelled"):
                return False
            j["cancel"] = True
            return True

    def active(self) -> List[Dict]:
        with self._lock:
            return [dict(j, events=[]) for j in self._jobs.values() if j["status"] in ("queued", "running")]

    def get(self, job_id: str) -> Optional[Dict]:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def events_since(self, job_id: str, index: int) -> Tuple[List[Dict], str]:
        """Return (new_events, status) for WebSocket streaming."""
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return [], "unknown"
            return list(j["events"][index:]), j["status"]

    def start_ingest(
        self,
        paths: List[str],
        config: Dict,
        db_path: Optional[Path] = None,
        engine_factory: Optional[EngineFactory] = None,
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = {
            "id": job_id, "status": "queued", "paths": paths,
            "folders": 0, "saved": 0, "events": [], "error": None,
            "started_at": time.time(), "finished_at": None, "cancel": False,
        }
        with self._lock:
            self._jobs[job_id] = job

        def _stop() -> bool:
            with self._lock:
                return bool(self._jobs[job_id].get("cancel"))

        def _run():
            if not self._run_lock.acquire(blocking=False):
                self._append(job_id, {"kind": "queued", "message": "Waiting for the current analysis to finish…"})
                self._run_lock.acquire()
            try:
                _run_locked()
            finally:
                self._run_lock.release()

        def _run_locked():
            if _stop():
                self._set(job_id, status="cancelled", finished_at=time.time())
                return
            self._set(job_id, status="running")
            try:
                engine, escalation = (engine_factory or build_engines)(config)
            except Exception as exc:  # misconfiguration (e.g. missing key)
                self._set(job_id, status="failed", error=str(exc), finished_at=time.time())
                self._append(job_id, {"kind": "error", "message": str(exc)})
                return
            problem = preflight(engine) if engine_factory is None else None
            if problem:
                self._set(job_id, status="failed", error=problem, finished_at=time.time())
                self._append(job_id, {"kind": "error", "message": problem})
                return

            def on_progress(ev: runner.ProgressEvent):
                self._append(job_id, asdict(ev))
                if ev.kind == "folder_done":
                    self._bump(job_id, saved_delta=ev.done)

            try:
                result = runner.process_batch(
                    paths, engine, db_path=db_path, escalation_engine=escalation,
                    ocr_backend=config.get("ocr_backend", "tesseract"),
                    concurrency=config.get("concurrency"), progress=on_progress,
                    should_stop=_stop,
                )
                self._set(job_id, status="cancelled" if result.get("cancelled") else "completed",
                          folders=result["folders"],
                          saved=result["saved"], finished_at=time.time())
            except Exception as exc:  # noqa: BLE001
                self._set(job_id, status="failed", error=str(exc), finished_at=time.time())
                self._append(job_id, {"kind": "error", "message": str(exc)})

        threading.Thread(target=_run, daemon=True).start()
        return job_id

    # ------------------------------------------------------------------ #
    def _set(self, job_id: str, **fields):
        with self._lock:
            self._jobs[job_id].update(fields)

    def _append(self, job_id: str, event: Dict):
        with self._lock:
            self._jobs[job_id]["events"].append(event)

    def _bump(self, job_id: str, saved_delta: int = 0):
        with self._lock:
            self._jobs[job_id]["saved"] += saved_delta
