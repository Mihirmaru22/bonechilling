"""API tests via FastAPI TestClient — in-memory keyring, injected fake engine."""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- isolate config/keyring/db BEFORE importing settings-using modules ------ #
import os
_TMP = Path(tempfile.mkdtemp(prefix="bc_api_"))
os.environ["BONECHILLING_HOME"] = str(_TMP)
os.environ["BONECHILLING_CONFIG"] = str(_TMP / "config.json")

import keyring
from keyring.backend import KeyringBackend


class MemKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def set_password(self, service, user, password):
        self.store[(service, user)] = password

    def get_password(self, service, user):
        return self.store.get((service, user))

    def delete_password(self, service, user):
        self.store.pop((service, user), None)


keyring.set_keyring(MemKeyring())

from fastapi.testclient import TestClient
from bonechiling.api.server import create_app
from bonechiling.core.schema import XrayFacts, LabelReading
from bonechiling.engines.base import EngineConfig, EngineResult
from test_pipeline import FakeEngine  # reuse

REPO = Path(__file__).resolve().parents[1]
TOKEN = "test-token-123"
H = {"X-API-Token": TOKEN}


def _fake_factory(config):
    facts = XrayFacts(image_type="X-ray", body_part="elbow", views=["AP"],
                      label=LabelReading(name="API TEST"), confidence=0.9)
    return FakeEngine(facts), None


def _client(db_path):
    return TestClient(create_app(token=TOKEN, db_path=db_path, engine_factory=_fake_factory))


def test_health_no_auth():
    c = _client(_TMP / "h.db")
    r = c.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_auth_required():
    c = _client(_TMP / "a.db")
    assert c.get("/settings").status_code == 401            # no token
    assert c.get("/settings", headers={"X-API-Token": "wrong"}).status_code == 401
    assert c.get("/settings", headers=H).status_code == 200


def test_settings_roundtrip():
    c = _client(_TMP / "s.db")
    r = c.post("/settings", headers=H, json={"provider": "openrouter", "cloud_notice_ack": True})
    assert r.json()["provider"] == "openrouter"
    assert c.get("/settings", headers=H).json()["cloud_notice_ack"] is True


def test_api_key_lifecycle():
    c = _client(_TMP / "k.db")
    # provider shows no key initially
    prov = {p["key"]: p for p in c.get("/providers", headers=H).json()}
    assert prov["openai"]["has_key"] is False
    # store
    assert c.post("/api-keys", headers=H, json={"provider": "openai", "key": "sk-x"}).json()["stored"]
    prov = {p["key"]: p for p in c.get("/providers", headers=H).json()}
    assert prov["openai"]["has_key"] is True
    # settings never leaks the key value
    body = c.get("/settings", headers=H).json()
    assert "sk-x" not in str(body)
    assert body["has_keys"]["openai"] is True
    # delete
    assert c.delete("/api-keys/openai", headers=H).json()["deleted"]
    prov = {p["key"]: p for p in c.get("/providers", headers=H).json()}
    assert prov["openai"]["has_key"] is False


def test_engine_test_missing_key():
    c = _client(_TMP / "e.db")
    r = c.post("/engine-test", headers=H, json={"provider": "anthropic"})
    assert r.status_code == 400  # needs key, none stored


def test_ingest_job_and_patients():
    # one-image folder so the job finishes fast
    folder = _TMP / "patientX"
    folder.mkdir(exist_ok=True)
    src = sorted((REPO / "test" / "1").glob("*.jpg"))[0]
    shutil.copy(src, folder / src.name)

    db = _TMP / "ingest.db"
    c = _client(db)
    jid = c.post("/ingest", headers=H, json={"paths": [str(folder)]}).json()["job_id"]

    status = None
    for _ in range(120):
        status = c.get(f"/jobs/{jid}", headers=H).json()
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(0.5)
    assert status["status"] == "completed", status
    assert status["saved"] == 1, status

    patients = c.get("/patients", headers=H).json()
    assert len(patients) == 1 and patients[0]["image_count"] == 1, patients
    detail = c.get(f"/patients/{patients[0]['id']}", headers=H).json()
    assert detail["images"][0]["engine_used"].startswith("fake"), detail


def _seed_patient(db_path):
    """Seed one patient + image directly (fast, no OCR)."""
    from bonechiling.data import db as db_mod
    from bonechiling.core.schema import XrayFacts, HardwareItem, LabelReading

    conn = db_mod.connect(db_path)
    pid = db_mod.get_or_create_patient_for_folder(conn, "/seed/alpha", "SEED ALPHA")
    facts = XrayFacts(image_type="X-ray", body_part="olecranon", views=["AP", "LAT"],
                      hardware=[HardwareItem(implant="olecranon plate", location="olecranon", count=1)],
                      impression="Olecranon AP/LAT; plate intact.", label=LabelReading(name="SEED ALPHA"))
    db_mod.save_analysis(conn, pid, {
        "file_path": "/seed/alpha/a.jpg", "file_sha256": "seedsha1", "raw_ocr": [],
        "facts": facts, "crosscheck": {}, "film_found": False, "engine": "fake:model",
        "model_name": "model", "latency_ms": 1, "error": None, "raw_response": None,
    })
    conn.close()
    return pid


def test_review_roundtrip():
    db = _TMP / "review.db"
    pid = _seed_patient(db)
    c = _client(db)
    # detail now carries patient record + reconciled hardware
    detail = c.get(f"/patients/{pid}", headers=H).json()
    assert detail["patient"]["review_status"] == "unreviewed"
    assert any("orthogonal" in s.lower() for s in detail["reconciled_hardware"]), detail["reconciled_hardware"]
    # submit a review
    r = c.post(f"/patients/{pid}/review", headers=H,
               json={"review_status": "verified", "surgeon_notes": "looks good"})
    assert r.json()["review_status"] == "verified"
    # persisted
    again = c.get(f"/patients/{pid}", headers=H).json()["patient"]
    assert again["review_status"] == "verified" and again["surgeon_notes"] == "looks good"
    assert again["reviewed_at"]


def test_export_xlsx():
    import io
    from openpyxl import load_workbook

    db = _TMP / "export.db"
    _seed_patient(db)
    c = _client(db)
    r = c.get("/export.xlsx", headers=H)
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    assert ws.cell(1, 1).value == "Patient"
    assert ws.cell(2, 1).value == "SEED ALPHA", ws.cell(2, 1).value
    # reconciled hardware column populated
    assert "plate" in str(ws.cell(2, 7).value).lower(), ws.cell(2, 7).value


def test_ws_bad_token_rejected():
    c = _client(_TMP / "ws.db")
    try:
        with c.websocket_connect("/ws/jobs/none?token=wrong") as ws:
            ws.receive_json()
        raised = False
    except Exception:
        raised = True
    assert raised, "WS with bad token should be rejected/closed"


def test_ws_streams_events():
    # Start a real (fake-engine) job and confirm the WS streams to job_end.
    folder = _TMP / "patientWS"
    folder.mkdir(exist_ok=True)
    src = sorted((REPO / "test" / "1").glob("*.jpg"))[0]
    shutil.copy(src, folder / src.name)
    c = _client(_TMP / "wsok.db")
    jid = c.post("/ingest", headers=H, json={"paths": [str(folder)]}).json()["job_id"]
    kinds = []
    with c.websocket_connect(f"/ws/jobs/{jid}?token={TOKEN}") as ws:
        for _ in range(200):
            ev = ws.receive_json()
            kinds.append(ev.get("kind"))
            if ev.get("kind") == "job_end":
                break
    assert "job_end" in kinds, kinds
    assert any(k in ("folder_start", "image_done", "folder_done") for k in kinds), kinds


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
