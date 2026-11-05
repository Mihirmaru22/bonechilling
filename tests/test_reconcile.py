"""Tests for core.reconcile cross-projection hardware dedup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.core.reconcile import reconcile_hardware, are_orthogonal, parse_views


def test_orthogonal_dedup():
    # Same plate seen on AP and on LAT must count ONCE, confirmed orthogonally.
    films = [
        {"views": '["AP"]', "body_part": "olecranon",
         "hardware": '[{"implant": "olecranon plate", "location": "olecranon", "count": 1, "integrity": "intact"}]'},
        {"views": '["LAT"]', "body_part": "olecranon",
         "hardware": '[{"implant": "olecranon plate", "location": "olecranon", "count": 1, "integrity": "intact"}]'},
    ]
    out = reconcile_hardware(films)
    assert len(out) == 1, out
    assert "orthogonal" in out[0].lower(), out[0]
    assert out[0].lower().startswith("1 "), out[0]  # counted once, not twice


def test_string_hardware_and_screws():
    films = [{"views": '["AP","LAT"]', "body_part": "radius",
              "hardware": '["1 distal radius plate with 4 cortical screws (intact)"]'}]
    out = reconcile_hardware(films)
    assert any("screw" in s.lower() for s in out), out


def test_no_hardware():
    out = reconcile_hardware([{"views": '["AP"]', "body_part": "femur", "hardware": "[]"}])
    assert out == ["No orthopaedic implants or surgical hardware identified."]


def test_view_parsing():
    assert parse_views('["AP","LAT"]') == {"AP", "LAT"}
    assert are_orthogonal({"AP", "LAT"}) is True
    assert are_orthogonal({"AP"}) is False


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
