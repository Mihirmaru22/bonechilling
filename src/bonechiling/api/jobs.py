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


class JobManager:
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._lock = threading.Lock()

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
            "started_at": time.time(), "finished_at": None,
        }
        with self._lock:
            self._jobs[job_id] = job

        def _run():
            self._set(job_id, status="running")
            try:
                engine, escalation = (engine_factory or build_engines)(config)
            except Exception as exc:  # misconfiguration (e.g. missing key)
                self._set(job_id, status="failed", error=str(exc), finished_at=time.time())
                self._append(job_id, {"kind": "error", "message": str(exc)})
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
                )
                self._set(job_id, status="completed", folders=result["folders"],
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
