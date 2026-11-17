"""server.py — local FastAPI backend for the desktop app.

Security: this serves patient data, so the launcher binds it to 127.0.0.1 only
and every request must carry the per-launch token (X-API-Token header, or
?token= for the WebSocket). The token is generated per process and handed to
the webview at startup. /health is the only unauthenticated route.
"""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core.reconcile import reconcile_patient_images
from ..data import db as db_mod
from ..data import export as export_mod
from ..data import settings as settings_mod
from ..engines.catalog import build_options
from ..pipeline.runner import clean_path as runner_clean, refresh_patient_demographics
from ..engines.registry import PRESETS, build_engine, config_from_preset, list_models
from . import ollama_helper
from .jobs import JobManager

__version__ = "0.2.0"


# ----- request bodies ------------------------------------------------------ #
class SettingsUpdate(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    escalate_provider: Optional[str] = None
    escalate_model: Optional[str] = None
    ocr_backend: Optional[str] = None
    concurrency: Optional[int] = None
    cloud_notice_ack: Optional[bool] = None


class ApiKeyBody(BaseModel):
    provider: str
    key: str


class EngineTestBody(BaseModel):
    provider: str
    model: Optional[str] = None
    key: Optional[str] = None     # if omitted, use the stored key
    store: bool = False           # store the key on success


class IngestBody(BaseModel):
    paths: List[str]


class ReanalyzeBody(BaseModel):
    scope: str = "failed"            # "failed" | "all" | "image"
    image_id: Optional[int] = None


class ReviewBody(BaseModel):
    review_status: Optional[str] = None
    surgeon_notes: Optional[str] = None
    verified_hardware: Optional[str] = None
    verified_facts: Optional[str] = None


def create_app(
    token: Optional[str] = None,
    db_path: Optional[Path] = None,
    engine_factory=None,
) -> FastAPI:
    app = FastAPI(title="BoneChilling", version=__version__)
    app.state.token = token or secrets.token_urlsafe(24)
    app.state.db_path = db_path
    app.state.engine_factory = engine_factory
    app.state.jobs = JobManager()

    def _db():
        return db_mod.connect(app.state.db_path)

    def auth(x_api_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_api_token, app.state.token):
            raise HTTPException(status_code=401, detail="invalid or missing API token")

    # ----- unauthenticated ------------------------------------------- #
    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    # ----- providers / settings -------------------------------------- #
    @app.get("/providers", dependencies=[Depends(auth)])
    def providers():
        return [
            {
                "key": p.key, "label": p.label, "default_model": p.default_model,
                "needs_key": p.needs_key, "notes": p.notes,
                "has_key": settings_mod.has_api_key(p.key) if p.needs_key else True,
            }
            for p in PRESETS.values()
        ]

    @app.get("/settings", dependencies=[Depends(auth)])
    def get_settings():
        cfg = settings_mod.load_config()
        cfg["has_keys"] = {k: settings_mod.has_api_key(k) for k, p in PRESETS.items() if p.needs_key}
        return cfg

    @app.post("/settings", dependencies=[Depends(auth)])
    def post_settings(body: SettingsUpdate):
        return settings_mod.save_config(body.model_dump(exclude_none=True))

    @app.get("/models", dependencies=[Depends(auth)])
    def models(provider: str):
        """Available models for a provider — to populate the model selector.
        Local (Ollama): installed models. Cloud: live /models if a key is stored."""
        preset = PRESETS.get(provider)
        if preset is None:
            raise HTTPException(400, f"unknown provider '{provider}'")
        if provider == "ollama":
            installed = ollama_helper.status().get("models", [])
            return {"models": installed, "default": preset.default_model,
                    "options": build_options("ollama", None, installed), "verified": True}
        key = settings_mod.get_api_key(provider) if preset.needs_key else None
        found = list_models(config_from_preset(provider, api_key=key)) if (key or not preset.needs_key) else []
        return {"models": found, "default": preset.default_model,
                "options": build_options(provider, found), "verified": bool(found)}

    # ----- API keys (write-only; never returned) --------------------- #
    @app.post("/api-keys", dependencies=[Depends(auth)])
    def set_key(body: ApiKeyBody):
        if body.provider not in PRESETS:
            raise HTTPException(400, f"unknown provider '{body.provider}'")
        try:
            settings_mod.set_api_key(body.provider, body.key)
        except settings_mod.KeyStoreError as exc:
            raise HTTPException(503, str(exc))
        return {"provider": body.provider, "stored": True}

    @app.delete("/api-keys/{provider}", dependencies=[Depends(auth)])
    def del_key(provider: str):
        return {"provider": provider, "deleted": settings_mod.delete_api_key(provider)}

    @app.post("/engine-test", dependencies=[Depends(auth)])
    def engine_test(body: EngineTestBody):
        preset = PRESETS.get(body.provider)
        if preset is None:
            raise HTTPException(400, f"unknown provider '{body.provider}'")
        key = body.key or (settings_mod.get_api_key(body.provider) if preset.needs_key else None)
        if preset.needs_key and not key:
            raise HTTPException(400, "no API key provided or stored for this provider")
        engine = build_engine(config_from_preset(body.provider, model=body.model, api_key=key))
        ok, detail = engine.health_check()
        if ok and body.store and key:
            try:
                settings_mod.set_api_key(body.provider, key)
            except settings_mod.KeyStoreError as exc:
                raise HTTPException(503, str(exc))
        return {"ok": ok, "detail": detail,
                "models": list_models(engine.config) if ok else [],
                "stored": bool(ok and body.store and key)}

    # ----- local AI (Ollama) setup helper ---------------------------- #
    @app.get("/ollama/status", dependencies=[Depends(auth)])
    def ollama_status():
        return ollama_helper.status()

    @app.post("/ollama/pull", dependencies=[Depends(auth)])
    def ollama_pull(body: Optional[dict] = None):
        model = (body or {}).get("model") or ollama_helper.RECOMMENDED_MODEL
        try:
            return ollama_helper.start_pull(model)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc))

    # ----- ingest jobs ----------------------------------------------- #
    @app.post("/ingest", dependencies=[Depends(auth)])
    def ingest(body: IngestBody):
        paths = [p for p in (runner_clean(x) for x in body.paths) if p]
        if not paths:
            raise HTTPException(400, "no paths given")
        body.paths = list(dict.fromkeys(paths))   # de-duplicate, keep order
        cfg = settings_mod.load_config()
        job_id = app.state.jobs.start_ingest(
            body.paths, cfg, db_path=app.state.db_path, engine_factory=app.state.engine_factory
        )
        return {"job_id": job_id}

    @app.post("/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    def cancel_job(job_id: str):
        if not app.state.jobs.get(job_id):
            raise HTTPException(404, "unknown job")
        return {"cancelling": app.state.jobs.cancel(job_id)}

    @app.get("/jobs", dependencies=[Depends(auth)])
    def active_jobs():
        return app.state.jobs.active()

    @app.get("/jobs/{job_id}", dependencies=[Depends(auth)])
    def job_status(job_id: str):
        job = app.state.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "unknown job")
        # recent events only; full log streams over the WebSocket
        return {**{k: v for k, v in job.items() if k != "events"},
                "event_count": len(job["events"]), "recent": job["events"][-10:]}

    # ----- patients -------------------------------------------------- #
    @app.get("/patients", dependencies=[Depends(auth)])
    def patients():
        conn = _db()
        try:
            return db_mod.list_patients(conn)
        finally:
            conn.close()

    @app.get("/patients/{patient_id}", dependencies=[Depends(auth)])
    def patient(patient_id: int):
        conn = _db()
        try:
            p = db_mod.get_patient(conn, patient_id)
            if not p:
                raise HTTPException(404, "unknown patient")
            imgs = db_mod.get_patient_images(conn, patient_id)
            return {
                "patient": p,
                "images": imgs,
                "reconciled_hardware": reconcile_patient_images(imgs),
            }
        finally:
            conn.close()

    @app.post("/patients/{patient_id}/review", dependencies=[Depends(auth)])
    def review(patient_id: int, body: ReviewBody):
        conn = _db()
        try:
            if not db_mod.get_patient(conn, patient_id):
                raise HTTPException(404, "unknown patient")
            db_mod.update_patient_review(conn, patient_id, **body.model_dump(exclude_none=True))
            return db_mod.get_patient(conn, patient_id)
        finally:
            conn.close()

    # ----- correcting data: remove / re-analyze --------------------- #
    # Only database rows are removed; the image files on disk are never touched.
    @app.delete("/patients/{patient_id}", dependencies=[Depends(auth)])
    def remove_patient(patient_id: int):
        conn = _db()
        try:
            if not db_mod.get_patient(conn, patient_id):
                raise HTTPException(404, "unknown patient")
            return {"deleted": True, "films_removed": db_mod.delete_patient(conn, patient_id)}
        finally:
            conn.close()

    @app.delete("/images/{image_id}", dependencies=[Depends(auth)])
    def remove_image(image_id: int):
        conn = _db()
        try:
            img = db_mod.get_image(conn, image_id)
            if not img:
                raise HTTPException(404, "unknown film")
            ok = db_mod.delete_images(conn, [image_id]) == 1
            refresh_patient_demographics(conn, img["patient_id"])
            return {"deleted": ok}
        finally:
            conn.close()

    @app.post("/patients/{patient_id}/reanalyze", dependencies=[Depends(auth)])
    def reanalyze(patient_id: int, body: ReanalyzeBody):
        """Drop the chosen results, then re-ingest the folder: ingest skips films
        still stored, so exactly the dropped ones are read again."""
        conn = _db()
        try:
            p = db_mod.get_patient(conn, patient_id)
            if not p:
                raise HTTPException(404, "unknown patient")
            folder = p.get("folder_path") or ""
            if not Path(folder).is_dir():
                raise HTTPException(409, f"The folder is no longer on this PC: {folder}")
            if body.scope == "image":
                img = db_mod.get_image(conn, body.image_id or -1)
                if not img or img["patient_id"] != patient_id:
                    raise HTTPException(404, "unknown film for this patient")
                if not Path(img.get("file_path") or "").is_file():
                    raise HTTPException(409, f"The image file is no longer on this PC: {img.get('file_path')}")
                ids = [img["id"]]
            elif body.scope in ("failed", "all"):
                ids = db_mod.patient_image_ids(conn, patient_id, failed_only=body.scope == "failed")
            else:
                raise HTTPException(400, "scope must be 'failed', 'all' or 'image'")
            removed = db_mod.delete_images(conn, ids)
            # results changed, so any earlier sign-off no longer applies
            db_mod.update_patient_review(conn, patient_id, review_status="unreviewed")
        finally:
            conn.close()
        cfg = settings_mod.load_config()
        job_id = app.state.jobs.start_ingest(
            [folder], cfg, db_path=app.state.db_path, engine_factory=app.state.engine_factory
        )
        return {"job_id": job_id, "films_queued": removed}

    @app.get("/export.xlsx", dependencies=[Depends(auth)])
    def export_xlsx():
        conn = _db()
        try:
            data = export_mod.export_bytes(conn)
        finally:
            conn.close()
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="patient_studies.xlsx"'},
        )

    # ----- progress WebSocket (token via query param) ---------------- #
    @app.websocket("/ws/jobs/{job_id}")
    async def ws_job(websocket: WebSocket, job_id: str):
        if not secrets.compare_digest(websocket.query_params.get("token", ""), app.state.token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        idx = 0
        try:
            while True:
                events, status = app.state.jobs.events_since(job_id, idx)
                for ev in events:
                    await websocket.send_json(ev)
                idx += len(events)
                if status in ("completed", "failed", "cancelled", "unknown"):
                    await websocket.send_json({"kind": "job_end", "status": status})
                    break
                await asyncio.sleep(0.25)
        except WebSocketDisconnect:
            pass

    # ----- static SPA (mounted LAST so API routes win) --------------- #
    ui_dir = Path(__file__).resolve().parent.parent / "webui"
    if ui_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")

    return app
