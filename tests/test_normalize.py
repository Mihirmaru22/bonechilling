"""Regression tests for core.normalize. Runs under pytest or as a plain script."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.core.normalize import SAMPLE_LINES, normalize


def test_frozen_sample():
    out = normalize(SAMPLE_LINES)
    assert out["name"] == "KARSHANBHAI BHARVAD", out["name"]
    assert out["age"] == "35", out["age"]
    assert out["sex"] == "M", out["sex"]
    assert out["body_part"] == "elbow", out["body_part"]
    assert set(out["views"]) == {"AP", "LAT"}, out["views"]
    assert "HOSPITAL" in (out["hospital"] or "").upper(), out["hospital"]
    assert out["study_date"] == "2026-01-02", out["study_date"]  # 02/01/2026 day-first
    assert out["fields"]["sex"]["confidence"] >= 0.8


def test_iso_date_and_misspelled_bodypart():
    out = normalize(["Femer AP 2025-03-14", "JOHN DOE 40 years / M 998877"])
    assert out["study_date"] == "2025-03-14", out["study_date"]
    assert out["body_part"] == "femur", out["body_part"]      # 'Femer' -> canonical
    assert out["name"] == "JOHN DOE" and out["sex"] == "M"
    assert out["patient_id"] == "998877", out["patient_id"]


def test_unambiguous_day_first():
    out = normalize(["Knee LAT 25/12/2024"])
    assert out["study_date"] == "2024-12-25", out["study_date"]  # 25 can't be a month
    assert out["fields"]["study_date"]["confidence"] >= 0.8


def test_no_person_line_warns():
    out = normalize(["Chest PA", "SOME HOSPITAL"])
    assert out["name"] is None
    assert any("no person line" in w for w in out["warnings"]), out["warnings"]


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
            passed += 1
    print(f"\n{passed} tests passed")
