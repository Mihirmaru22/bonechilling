"""End-to-end pipeline tests with a fake engine (no network) + temp DB."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.data import db as db_mod
from bonechiling.engines.base import EngineConfig, EngineResult
from bonechiling.core.schema import XrayFacts, LabelReading
from bonechiling.pipeline import runner

REPO = Path(__file__).resolve().parents[1]
FOLDER = REPO / "test" / "1"


class FakeEngine:
    """Returns a canned XrayFacts; records how many times it was called."""

    def __init__(self, facts: XrayFacts, local=True, name="fake:model"):
        self.config = EngineConfig(provider="ollama" if local else "openai",
                                   model="model", base_url="http://x", api_key=None)
        self._facts = facts
        self._name = name
        self.calls = 0

    def analyze(self, image):
        self.calls += 1
        return EngineResult(facts=self._facts, engine=self._name, latency_ms=5)

    def health_check(self):
        return True, "ok"


def _xray(**kw):
    base = dict(image_type="X-ray", body_part="elbow", views=["AP"], confidence=0.9)
    base.update(kw)
    return XrayFacts(**base)


# --------------------------------------------------------------------------- #
def test_discover_folders():
    folders = runner.discover_patient_folders([str(REPO / "test")])
    names = {f.name for f in folders}
    assert {"1", "2", "3", "4"}.issubset(names), names


def test_collect_demographics_prefers_complete_name():
    # Two films of one folder: a truncated OCR miss and the full name.
    acc = {}
    runner._collect_demographics(acc, {"crosscheck": {"name": {"value": "I SOLANKI", "status": "ocr_only"}}})
    runner._collect_demographics(acc, {"crosscheck": {"name": {"value": "JAYANTIBHAI SOLANKI", "status": "ocr_only"}}})
    assert acc["name"] == "JAYANTIBHAI SOLANKI", acc
    # a verified reading still wins even if shorter
    runner._collect_demographics(acc, {"crosscheck": {"name": {"value": "J SOLANKI", "status": "verified"}}})
    assert acc["name"] == "J SOLANKI", acc


def test_should_escalate():
    good = _xray()
    cc_ok = {"name": type("A", (), {"status": "verified"})()}
    r_ok = EngineResult(facts=good, engine="e")
    assert runner.should_escalate(good, {}, r_ok) is False
    # validation failure -> escalate
    bad = XrayFacts(image_type="Unknown", limitations=["schema validation failed: X"])
    assert runner.should_escalate(bad, {}, EngineResult(facts=bad, engine="e")) is True
    # engine error -> escalate
    assert runner.should_escalate(good, {}, EngineResult(facts=good, engine="e", error="boom")) is True


def test_end_to_end_and_idempotency():
    with tempfile.TemporaryDirectory() as tmp:
        dbp = Path(tmp) / "t.db"
        conn = db_mod.connect(dbp)
        eng = FakeEngine(_xray(label=LabelReading(name="TEST PERSON", sex="Male")))

        r1 = runner.process_batch([str(FOLDER)], eng, conn=conn)
        assert r1["folders"] == 1, r1
        assert r1["saved"] >= 1, r1
        first_calls = eng.calls

        patients = db_mod.list_patients(conn)
        assert len(patients) == 1, patients
        p = patients[0]
        assert p["folder_path"].endswith("/1"), p["folder_path"]      # folder == identity
        assert p["image_count"] == r1["saved"], p

        imgs = db_mod.get_patient_images(conn, p["id"])
        assert all(i["file_sha256"] for i in imgs), "sha stored"
        assert any(i["engine_used"] == "fake:model" for i in imgs), "engine recorded"
        assert all(i["crosscheck_json"] for i in imgs), "crosscheck stored"

        # Re-run: nothing new saved (idempotent); engine not re-called for saved imgs.
        r2 = runner.process_batch([str(FOLDER)], eng, conn=conn)
        assert r2["saved"] == 0, f"idempotency broken: {r2}"
        assert eng.calls == first_calls, f"re-analyzed already-ingested images ({eng.calls} vs {first_calls})"
        assert len(db_mod.list_patients(conn)) == 1
        conn.close()
        print(f"   ingested {r1['saved']} films, engine calls={first_calls}, re-run saved=0")


def test_escalation_replaces_result():
    with tempfile.TemporaryDirectory() as tmp:
        conn = db_mod.connect(Path(tmp) / "t.db")
        # local returns a validation-failure facts -> must escalate
        local = FakeEngine(XrayFacts(image_type="Unknown", limitations=["schema validation failed"]),
                           local=True, name="ollama:small")
        cloud = FakeEngine(_xray(body_part="wrist"), local=False, name="openai:big")
        img = sorted(FOLDER.glob("*.jpg"))[0]
        rec = runner.analyze_image(img, local, escalation_engine=cloud)
        assert cloud.calls == 1, "cloud escalation engine was not called"
        assert "escalated" in rec["engine"], rec["engine"]
        assert rec["facts"].body_part == "wrist", "escalated result not used"
        conn.close()


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
