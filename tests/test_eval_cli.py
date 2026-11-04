"""Tests for the eval harness scoring and the CLI engine wiring."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.core.schema import XrayFacts, HardwareItem
from bonechiling.eval import harness
from bonechiling import cli
from bonechiling.engines.openai_compat import OpenAICompatEngine
from bonechiling.engines.anthropic_engine import AnthropicEngine


# ---- scoring (pure) ------------------------------------------------------- #
def test_views_f1():
    assert harness._views_f1(["AP", "LAT"], ["AP", "LAT"]) == 1.0
    assert harness._views_f1(["AP", "LAT"], ["LATERAL", "AP"]) == 1.0   # alias
    assert harness._views_f1(["AP", "LAT"], ["AP"]) < 1.0
    assert harness._views_f1([], []) == 1.0


def test_score_fields():
    facts = XrayFacts(image_type="X-ray", body_part="elbow", views=["AP", "LAT"],
                      hardware=[HardwareItem(implant="plate")])
    label = {"image_type": "X-ray", "body_part": "elbow", "views": ["AP", "LAT"],
             "name": "JOHN DOE", "hardware_present": True}
    s = harness.score_fields(label, facts, final_name="John Doe")
    assert s["image_type"] == 1.0
    assert s["body_part"] == 1.0
    assert s["views"] == 1.0
    assert s["name"] == 1.0
    assert s["hardware_present"] == 1.0

    # wrong answers score 0
    s2 = harness.score_fields({"body_part": "knee", "hardware_present": False}, facts, None)
    assert s2["body_part"] == 0.0
    assert s2["hardware_present"] == 0.0  # facts HAS hardware, label says none


def test_only_present_fields_scored():
    facts = XrayFacts(image_type="X-ray", body_part="hip")
    s = harness.score_fields({"body_part": "hip"}, facts, None)
    assert set(s.keys()) == {"body_part"}


def test_load_bootstrap_labels():
    labels = harness.load_labels(Path(__file__).resolve().parents[1] / "eval" / "labels.json")
    assert len(labels) == 19
    assert all("file" in l for l in labels)


# ---- CLI engine wiring (no network) --------------------------------------- #
def test_cli_parser_and_local_engine():
    args = cli.build_parser().parse_args(["ingest", "somedir", "--provider", "ollama"])
    assert args.command == "ingest" and args.provider == "ollama"
    eng = cli._make_engine("ollama", None, None)   # local needs no key
    assert isinstance(eng, OpenAICompatEngine)


def test_cli_cloud_requires_key():
    raised = False
    try:
        cli._make_engine("openai", None, None)   # no key, no env -> SystemExit
    except SystemExit:
        raised = True
    assert raised, "cloud provider without a key must exit with guidance"


def test_cli_key_from_arg():
    eng = cli._make_engine("anthropic", "claude-x", "sk-explicit")
    assert isinstance(eng, AnthropicEngine)
    assert eng.config.api_key == "sk-explicit"


def test_cli_key_from_env(monkeypatch=None):
    import os
    os.environ["OPENROUTER_API_KEY"] = "sk-env-123"
    try:
        eng = cli._make_engine("openrouter", None, None)
        assert eng.config.api_key == "sk-env-123"
    finally:
        del os.environ["OPENROUTER_API_KEY"]


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
