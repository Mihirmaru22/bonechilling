"""Tests for core.crosscheck — OCR vs VLM label reconciliation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.core.crosscheck import cross_check, has_conflicts
from bonechiling.core.schema import LabelReading


def test_agreement_verified():
    ocr = {"name": "KARSHANBHAI BHARVAD", "age": "35", "sex": "M", "patient_id": "020110"}
    vlm = LabelReading(name="Karshanbhai Bharvad", age="35", sex="Male", patient_id="020110")
    agr = cross_check(ocr, vlm)
    assert agr["name"].verified, agr["name"]
    assert agr["age"].verified and agr["sex"].verified
    assert agr["patient_id"].verified
    assert not has_conflicts(agr)


def test_name_token_tolerance():
    # OCR dropped a token / reordered — still a match above threshold.
    agr = cross_check({"name": "JAYANTIBHAI SOLANKI"}, LabelReading(name="Solanki Jayantibhai"))
    assert agr["name"].verified, agr["name"]


def test_conflict_flagged():
    agr = cross_check({"name": "JOHN DOE", "age": "40"}, LabelReading(name="JANE ROE", age="40"))
    assert agr["name"].status == "conflict", agr["name"]
    assert agr["age"].verified
    assert has_conflicts(agr)


def test_single_source():
    agr = cross_check({"name": "ONLY OCR"}, LabelReading())
    assert agr["name"].status == "ocr_only" and agr["name"].value == "ONLY OCR"
    agr = cross_check({}, LabelReading(name="ONLY VLM"))
    assert agr["name"].status == "vlm_only" and agr["name"].value == "ONLY VLM"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
