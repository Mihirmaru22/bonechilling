"""Film images, open-folder, saved-key masking/reveal, model lifecycle."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp())
os.environ["BONECHILLING_HOME"] = str(_TMP)
os.environ["BONECHILLING_CONFIG"] = str(_TMP / "config.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import keyring
from keyring.backend import KeyringBackend


class _MemKeyring(KeyringBackend):
    priority = 1
    _store = {}
    def set_password(self, s, u, p): self._store[(s, u)] = p
    def get_password(self, s, u): return self._store.get((s, u))
    def delete_password(self, s, u): self._store.pop((s, u), None)


keyring.set_keyring(_MemKeyring())

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from bonechiling.api import jobs as jobs_mod
from bonechiling.api import os_open
from bonechiling.api.server import create_app
from bonechiling.data import db as db_mod
from bonechiling.engines import catalog
from bonechiling.engines.base import EngineConfig, explain_http_error
from bonechiling.core.schema import XrayFacts

H = {"X-API-Token": "t"}


def _client(name):
    return TestClient(create_app(token="t", db_path=_TMP / name))


def _patient_with_film(dbname):
    d = _TMP / dbname.replace(".db", "")
    d.mkdir(exist_ok=True)
    img = d / "knee.png"
    Image.fromarray((np.random.default_rng(1).random((300, 200)) * 255).astype("uint8"), "L").save(img)
    conn = db_mod.connect(_TMP / dbname)
    try:
        pid = db_mod.get_or_create_patient_for_folder(conn, str(d))
        iid = db_mod.save_analysis(conn, pid, {"file_path": str(img), "file_sha256": dbname,
                                               "facts": XrayFacts(image_type="X-ray")})
    finally:
        conn.close()
    return pid, iid, d, img


def test_image_view_jpeg_and_auth():
    c = _client("img.db")
    pid, iid, d, img = _patient_with_film("img.db")
    r = c.get(f"/images/{iid}/view?size=100&token=t")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    from io import BytesIO
    assert max(Image.open(BytesIO(r.content)).size) <= 100
    assert c.get(f"/images/{iid}/view").status_code == 401           # no token
    assert c.get(f"/images/{iid}/view?token=wrong").status_code == 401
    assert c.get("/images/9999/view?token=t").status_code == 404
    img.unlink()
    r = c.get(f"/images/{iid}/view?token=t")
    assert r.status_code == 404 and "not found" in r.json()["detail"]


def test_open_folder_and_reveal():
    c = _client("open.db")
    pid, iid, d, img = _patient_with_film("open.db")
    calls = []
    real_f, real_r = os_open.open_folder, os_open.reveal_file
    os_open.open_folder = lambda p: calls.append(("folder", str(p))) if Path(p).is_dir() else (_ for _ in ()).throw(FileNotFoundError(p))
    os_open.reveal_file = lambda p: calls.append(("file", str(p))) if Path(p).is_file() else (_ for _ in ()).throw(FileNotFoundError(p))
    try:
        assert c.post(f"/patients/{pid}/open-folder", headers=H).status_code == 200
        assert c.post(f"/images/{iid}/reveal", headers=H).status_code == 200
        assert calls == [("folder", str(d)), ("file", str(img))]
        assert c.post("/patients/999/open-folder", headers=H).status_code == 404
        shutil.rmtree(d)
        assert c.post(f"/patients/{pid}/open-folder", headers=H).status_code == 409
        assert c.post(f"/images/{iid}/reveal", headers=H).status_code == 409
    finally:
        os_open.open_folder, os_open.reveal_file = real_f, real_r


def test_saved_key_masked_and_reveal():
    c = _client("keys.db")
    assert c.get("/api-keys/gemini", headers=H).json()["has_key"] is False
    c.post("/api-keys", json={"provider": "gemini", "key": "AIzaSyABCDEFGHIJ1234"}, headers=H)
    r = c.get("/api-keys/gemini", headers=H).json()
    assert r["has_key"] and r["masked"].startswith("AIza") and r["masked"].endswith("1234")
    assert "key" not in r and "ABCDEFGHIJ" not in r["masked"]
    assert c.get("/api-keys/gemini?reveal=true", headers=H).json()["key"] == "AIzaSyABCDEFGHIJ1234"
    assert c.get("/api-keys/gemini?reveal=true").status_code == 401
    assert c.get("/api-keys/bogus", headers=H).status_code == 400


def test_saved_model_status_states():
    s = catalog.saved_model_status
    assert s("openai", "gpt-x", ["gpt-x"])["state"] == "ok"
    assert s("openai", "gpt-x", [])["state"] == "unknown"
    assert s("openai", "gpt-x", ["gpt-y"])["state"] == "missing"
    dep = s("gemini", "gemini-2.0-flash", ["gemini-2.0-flash"])
    assert dep["state"] == "deprecated" and dep["replacement"] == "gemini-2.5-flash"
    assert s("ollama", "qwen2.5vl:3b", [], ["qwen2.5vl:3b"])["state"] == "ok"
    assert s("ollama", "llava:7b", [], ["qwen2.5vl:3b"])["state"] == "missing"
    assert s("ollama", None, [], [])["state"] == "ok"


def test_catalog_json_valid():
    allowed = {"current", "deprecated", "retired"}
    for m in catalog.OLLAMA_VISION + [m for v in catalog.CLOUD_SUGGESTED.values() for m in v]:
        assert m["id"] and m["label"] and m.get("status", "current") in allowed, m
        if m.get("status") in ("deprecated", "retired"):
            assert m.get("replacement"), m
    opts = catalog.build_options("gemini", ["gemini-2.0-flash", "gemini-2.5-flash"])
    assert next(o for o in opts if o["id"] == "gemini-2.0-flash")["lifecycle"] == "deprecated"


def test_explain_retired_model_error():
    msg = explain_http_error(404, '{"error":{"code":"model_not_found","message":"The model `gpt-9` does not exist"}}', "gpt-9")
    assert "isn't available from this provider any more" in msg and "Retry failed films" in msg
    assert "API key" in explain_http_error(401, "nope", "m")
    assert explain_http_error(500, "boom", "m").startswith("HTTP 500")


def test_preflight_blocks_retired_cloud_model():
    class E:
        config = EngineConfig(provider="openai", model="gpt-old", base_url="http://x", api_key="k")
        def health_check(self): return True, "ok"
    real = jobs_mod.__dict__.get("list_models")
    import bonechiling.engines.registry as reg
    orig = reg.list_models
    reg.list_models = lambda cfg, vision_only=True: ["gpt-new"]
    try:
        msg = jobs_mod.preflight(E())
        assert msg and "no longer offers 'gpt-old'" in msg
        reg.list_models = lambda cfg, vision_only=True: ["gpt-old"]
        assert jobs_mod.preflight(E()) is None
        reg.list_models = lambda cfg, vision_only=True: []      # can't verify -> don't block
        assert jobs_mod.preflight(E()) is None
    finally:
        reg.list_models = orig


if __name__ == "__main__":
    n = 0
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn(); print("PASS", name); n += 1
        print(f"\n{n} tests passed")
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
