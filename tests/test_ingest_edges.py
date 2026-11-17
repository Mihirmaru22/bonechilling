"""Ingest edge cases: retries, bad files, bad paths, cancellation, corrections.

Fake engine + generated images + temp DB, so no network or model is needed.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from PIL import Image

from bonechiling.core.imaging import open_image
from bonechiling.core.prefilter import PrefilterVerdict
from bonechiling.core.schema import LabelReading, XrayFacts
from bonechiling.data import db as db_mod
from bonechiling.engines.base import EngineConfig, EngineResult
from bonechiling.pipeline import runner

# Screening heuristics are tested elsewhere; here every generated image is "maybe".
runner.classify = lambda p: PrefilterVerdict.MAYBE


class Engine:
    """Fake engine. mode: ok | error | crash | nonxray. Name per call via names."""

    def __init__(self, mode="ok", names=None):
        self.config = EngineConfig(provider="ollama", model="m", base_url="http://x", api_key=None)
        self.mode, self.names, self.calls, self.hook = mode, list(names or []), 0, None

    def analyze(self, image):
        self.calls += 1
        if self.hook:
            self.hook(self.calls)
        if self.mode == "crash":
            raise RuntimeError("boom")
        if self.mode == "error":
            return EngineResult(facts=XrayFacts(image_type="X-ray"), engine="fake:m", error="HTTP 500: down")
        if self.mode == "nonxray":
            return EngineResult(facts=XrayFacts(image_type="Non-X-ray"), engine="fake:m")
        name = self.names.pop(0) if self.names else "TEST PERSON"
        return EngineResult(facts=XrayFacts(image_type="X-ray", body_part="knee",
                                            label=LabelReading(name=name)), engine="fake:m")

    def health_check(self):
        return True, "ok"


def _img(path: Path, seed: int, ext=".png"):
    rng = np.random.default_rng(seed)
    arr = (rng.random((64, 64)) * 255).astype("uint8")
    p = path.with_suffix(ext)
    Image.fromarray(arr, "L").save(p)
    return p


class Env:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = db_mod.connect(self.tmp / "t.db")

    def folder(self, name, n=2, start=0):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            _img(d / f"film{start + i}", seed=hash((name, start + i)) % 10_000)
        return d

    def run(self, paths, eng, **kw):
        events = []
        r = runner.process_batch(paths, eng, conn=self.conn, progress=events.append, **kw)
        return r, events

    def count(self, sql="SELECT COUNT(*) FROM images", *a):
        return self.conn.execute(sql, a).fetchone()[0]

    def close(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def _env(fn):
    def wrapper():
        e = Env()
        try:
            fn(e)
        finally:
            e.close()
    wrapper.__name__ = fn.__name__
    return wrapper


# --------------------------------------------------------------------------- #
@_env
def test_failed_films_are_retried(e):
    d = e.folder("P1", 2)
    r, ev = e.run([str(d)], Engine("error"))
    assert r["saved"] == 0 and e.count("SELECT COUNT(*) FROM images WHERE error IS NOT NULL") == 2
    assert any(x.kind == "image_failed" for x in ev)
    r, ev = e.run([str(d)], Engine("ok"))          # engine fixed: re-ingest retries
    assert r["saved"] == 2, r
    assert e.count() == 2 and e.count("SELECT COUNT(*) FROM images WHERE error IS NOT NULL") == 0
    assert sum(x.kind == "image_retry" for x in ev) == 2
    r, ev = e.run([str(d)], Engine("ok"))          # successful films are not redone
    assert r["saved"] == 0 and e.count() == 2


@_env
def test_crash_on_one_film_keeps_the_rest(e):
    d = e.folder("P1", 3)
    eng = Engine("ok")
    eng.hook = lambda n: (_ for _ in ()).throw(RuntimeError("bad file")) if n == 2 else None
    r, ev = e.run([str(d)], eng)
    assert r["saved"] == 2 and any(x.kind == "image_failed" for x in ev)


@_env
def test_unreadable_file_reported_not_fatal(e):
    d = e.folder("P1", 2)
    real = runner.sha256_file
    def flaky(p, *a):
        if Path(p).name.startswith("film0"):
            raise PermissionError(13, "Permission denied")
        return real(p, *a)
    runner.sha256_file = flaky
    try:
        r, ev = e.run([str(d)], Engine())
    finally:
        runner.sha256_file = real
    assert r["saved"] == 1
    assert any(x.kind == "error" and "can't read" in x.message for x in ev)


@_env
def test_bad_folder_does_not_stop_batch(e):
    a, b = e.folder("A", 1), e.folder("B", 1)
    real = runner.process_folder
    def maybe_fail(conn, folder, *a, **k):
        if Path(folder).name == "A":
            raise OSError("drive disconnected")
        return real(conn, folder, *a, **k)
    runner.process_folder = maybe_fail
    try:
        r, ev = e.run([str(e.tmp)], Engine())
    finally:
        runner.process_folder = real
    assert r["saved"] == 1
    assert any(x.kind == "error" and "A" in x.message for x in ev)


@_env
def test_pasted_paths_quotes_url_missing(e):
    d = e.folder("Quoted Name", 1)
    r, ev = e.run([f'  "{d}"  ', "file://" + str(d).replace(" ", "%20"), str(e.tmp / "nope")], Engine())
    assert r["folders"] == 1 and r["saved"] == 1, r
    assert any(x.kind == "error" and "Not found" in x.message for x in ev)


@_env
def test_folder_without_images_reported(e):
    empty = e.tmp / "notes"
    empty.mkdir()
    (empty / "readme.txt").write_text("x")
    r, ev = e.run([str(empty)], Engine())
    assert r["folders"] == 0
    assert any("No X-ray images" in x.message for x in ev)


@_env
def test_no_empty_patient_for_nonxray_folder(e):
    d = e.folder("Photos", 2)
    e.run([str(d)], Engine("nonxray"))
    assert e.count("SELECT COUNT(*) FROM patients") == 0


@_env
def test_changed_file_replaces_old_result(e):
    d = e.folder("P1", 1)
    e.run([str(d)], Engine())
    _img(d / "film0", seed=999)                     # same name, new pixels
    e.run([str(d)], Engine())
    assert e.count() == 1


@_env
def test_duplicate_in_other_folder_says_where(e):
    a = e.folder("A", 1)
    b = e.tmp / "B"
    b.mkdir()
    shutil.copy(next(a.iterdir()), b / "copy.png")
    r, ev = e.run([str(e.tmp)], Engine())
    assert any("already analyzed under A" in x.message for x in ev), [x.message for x in ev]
    assert e.count("SELECT COUNT(*) FROM patients") == 1  # B had nothing new -> no empty patient


@_env
def test_formats_tif_and_extensionless_dicom(e):
    d = e.tmp / "P"
    d.mkdir()
    _img(d / "scan", 1, ext=".tif")
    dcm = d / "IM0001"
    dcm.write_bytes(b"\0" * 128 + b"DICM" + b"\0" * 16)
    (d / "Thumbs.db").write_bytes(b"x")
    names = {f.name for f in d.iterdir() if runner.is_candidate(f)}
    assert names == {"scan.tif", "IM0001"}, names


@_env
def test_cancel_stops_early(e):
    d = e.folder("P1", 5)
    eng = Engine()
    stop = {"v": False}
    eng.hook = lambda n: stop.update(v=True) if n == 2 else None
    r, _ = e.run([str(d)], eng, should_stop=lambda: stop["v"])
    assert r["cancelled"] and r["saved"] == 2 and eng.calls == 2


@_env
def test_each_film_saved_immediately(e):
    d = e.folder("P1", 3)
    seen = []
    eng = Engine()
    eng.hook = lambda n: seen.append(e.count())
    e.run([str(d)], eng)
    assert seen == [0, 1, 2], seen


@_env
def test_demographics_keep_best_name_after_removal(e):
    d = e.folder("P1", 2)
    e.run([str(d)], Engine(names=["JAYANTIBHAI SOLANKI", "I SOLANKI"]))
    pid = e.conn.execute("SELECT id FROM patients").fetchone()[0]
    full = e.conn.execute("SELECT id FROM images WHERE label_json LIKE '%JAYANTIBHAI%'").fetchone()[0]
    assert db_mod.get_patient(e.conn, pid)["name"] == "JAYANTIBHAI SOLANKI"
    # re-reading only the worse film must not replace the good name
    db_mod.delete_images(e.conn, [i for i in db_mod.patient_image_ids(e.conn, pid) if i != full])
    e.run([str(d)], Engine(names=["I SOLANKI"]))
    assert db_mod.get_patient(e.conn, pid)["name"] == "JAYANTIBHAI SOLANKI"


@_env
def test_save_race_is_harmless(e):
    pid = db_mod.get_or_create_patient_for_folder(e.conn, "/x")
    rec = {"file_path": "/x/a.png", "file_sha256": "abc", "facts": XrayFacts(image_type="X-ray")}
    real = db_mod.image_exists
    db_mod.image_exists = lambda c, s: False       # both "jobs" pass the check
    try:
        assert db_mod.save_analysis(e.conn, pid, rec) is not None
        assert db_mod.save_analysis(e.conn, pid, rec) is None
    finally:
        db_mod.image_exists = real


def test_open_image_exif_and_16bit():
    tmp = Path(tempfile.mkdtemp())
    try:
        im = Image.new("L", (40, 20), 100)
        exif = im.getexif()
        exif[0x0112] = 6                            # rotate 90 on display
        im.save(tmp / "r.jpg", exif=exif)
        assert open_image(tmp / "r.jpg").size == (20, 40)
        arr = np.linspace(0, 4000, 64 * 64).reshape(64, 64).astype("uint16")
        Image.fromarray(arr).save(tmp / "w.png")
        o = open_image(tmp / "w.png")
        a = np.asarray(o)
        assert o.mode == "L" and a.min() == 0 and a.max() == 255
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_clean_path():
    assert runner.clean_path('  "C:\\X rays\\P1"  ') == "C:\\X rays\\P1"
    assert runner.clean_path("file:///C:/X%20rays/P1") == "C:/X rays/P1"
    assert runner.clean_path("file:///home/u/P1") == "/home/u/P1"
    assert runner.clean_path("   ") == ""


# ---- API: remove / re-analyze / jobs ------------------------------------- #
def test_api_remove_and_reanalyze():
    from fastapi.testclient import TestClient
    from bonechiling.api.server import create_app

    tmp = Path(tempfile.mkdtemp())
    eng = Engine("error")
    try:
        app = create_app(token="t", db_path=tmp / "a.db", engine_factory=lambda cfg: (eng, None))
        c = TestClient(app)
        H = {"X-API-Token": "t"}
        d = tmp / "P1"
        d.mkdir()
        for i in range(3):
            _img(d / f"f{i}", 50 + i)

        def wait(job):
            for _ in range(200):
                s = c.get(f"/jobs/{job}", headers=H).json()["status"]
                if s in ("completed", "failed", "cancelled"):
                    return s
                time.sleep(0.05)
            raise AssertionError("job did not finish")

        assert wait(c.post("/ingest", json={"paths": [f'"{d}"', str(d)]}, headers=H).json()["job_id"]) == "completed"
        pid = c.get("/patients", headers=H).json()[0]["id"]
        imgs = c.get(f"/patients/{pid}", headers=H).json()["images"]
        assert len(imgs) == 3 and all(i["error"] for i in imgs)

        c.post(f"/patients/{pid}/review", json={"review_status": "verified"}, headers=H)
        eng.mode = "ok"
        r = c.post(f"/patients/{pid}/reanalyze", json={"scope": "failed"}, headers=H).json()
        assert r["films_queued"] == 3 and wait(r["job_id"]) == "completed"
        p = c.get(f"/patients/{pid}", headers=H).json()
        assert not any(i["error"] for i in p["images"]) and len(p["images"]) == 3
        assert p["patient"]["review_status"] == "unreviewed"   # results changed -> sign-off reset

        one = p["images"][0]["id"]
        r = c.post(f"/patients/{pid}/reanalyze", json={"scope": "image", "image_id": one}, headers=H).json()
        assert r["films_queued"] == 1 and wait(r["job_id"]) == "completed"
        assert len(c.get(f"/patients/{pid}", headers=H).json()["images"]) == 3

        r = c.post(f"/patients/{pid}/reanalyze", json={"scope": "all"}, headers=H).json()
        assert r["films_queued"] == 3 and wait(r["job_id"]) == "completed"

        img = c.get(f"/patients/{pid}", headers=H).json()["images"][0]["id"]
        assert c.delete(f"/images/{img}", headers=H).json()["deleted"]
        assert len(c.get(f"/patients/{pid}", headers=H).json()["images"]) == 2
        assert c.delete("/images/999999", headers=H).status_code == 404
        assert (d / "f0.png").exists()                       # files on disk untouched

        assert c.post(f"/patients/{pid}/reanalyze", json={"scope": "nope"}, headers=H).status_code == 400
        assert c.delete(f"/patients/{pid}", headers=H).json()["deleted"]
        assert c.get("/patients", headers=H).json() == []
        assert c.delete(f"/patients/{pid}", headers=H).status_code == 404
        assert len(list(d.iterdir())) == 3

        # re-analyze a patient whose folder was moved away
        assert wait(c.post("/ingest", json={"paths": [str(d)]}, headers=H).json()["job_id"]) == "completed"
        pid = c.get("/patients", headers=H).json()[0]["id"]
        shutil.move(str(d), str(tmp / "moved"))
        assert c.post(f"/patients/{pid}/reanalyze", json={"scope": "all"}, headers=H).status_code == 409

        assert c.post("/ingest", json={"paths": ["  ", '""']}, headers=H).status_code == 400
        assert c.post("/jobs/none/cancel", headers=H).status_code == 404
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_jobs_queue_and_cancel():
    from bonechiling.api.jobs import JobManager

    tmp = Path(tempfile.mkdtemp())
    try:
        d = tmp / "P"
        d.mkdir()
        for i in range(4):
            _img(d / f"f{i}", 200 + i)
        slow = Engine()
        slow.hook = lambda n: time.sleep(0.15)
        jm = JobManager()
        f = lambda cfg: (slow, None)
        j1 = jm.start_ingest([str(d)], {}, db_path=tmp / "q.db", engine_factory=f)
        j2 = jm.start_ingest([str(d)], {}, db_path=tmp / "q.db", engine_factory=f)
        time.sleep(0.05)
        assert jm.get(j2)["status"] == "queued"
        assert jm.cancel(j1)
        for _ in range(200):
            if jm.get(j1)["status"] in ("cancelled", "completed") and jm.get(j2)["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert jm.get(j1)["status"] == "cancelled"
        assert jm.get(j2)["status"] == "completed"
        conn = db_mod.connect(tmp / "q.db")
        try:
            n = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
            dup = conn.execute("SELECT COUNT(*) - COUNT(DISTINCT file_sha256) FROM images").fetchone()[0]
        finally:
            conn.close()
        assert n == 4 and dup == 0, (n, dup)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
