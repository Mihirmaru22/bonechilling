"""Model picker catalog: curated lists, live-list merge, vision filtering (no network)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.engines.catalog import OLLAMA_VISION, build_options, looks_vision_capable
from bonechiling.engines.registry import PRESETS


def test_ollama_list_size_and_tags():
    assert 10 <= len(OLLAMA_VISION) <= 20
    ids = [m["id"] for m in OLLAMA_VISION]
    assert len(ids) == len(set(ids)), "duplicate tags"
    for i in ids:
        assert ":" in i and " " not in i and i == i.lower(), i
    assert PRESETS["ollama"].default_model in ids


def test_ollama_installed_status_and_extras():
    opts = build_options("ollama", None, ["qwen2.5vl:3b", "my-custom:latest"])
    by = {o["id"]: o for o in opts}
    assert by["qwen2.5vl:3b"]["status"] == "installed"
    assert by["gemma3:4b"]["status"] == "download"
    assert by["my-custom:latest"]["group"] == "Other installed models"


def test_cloud_suggested_without_key():
    opts = build_options("openai", [])
    assert opts and all(o["status"] == "suggested" for o in opts)


def test_cloud_live_list_wins():
    opts = build_options("openai", ["gpt-4o", "gpt-new-vision"])
    ids = [o["id"] for o in opts]
    assert "gpt-4o" in ids and "gpt-new-vision" in ids
    assert "gpt-4.1" not in ids, "suggestions not offered by the account are dropped"
    assert all(o["status"] == "available" for o in opts)


def test_vision_heuristic():
    assert looks_vision_capable("openai", "gpt-4o-mini")
    assert not looks_vision_capable("openai", "text-embedding-3-small")
    assert not looks_vision_capable("openai", "gpt-4o-mini-tts")
    assert looks_vision_capable("gemini", "gemini-2.5-flash")
    assert not looks_vision_capable("gemini", "text-embedding-004")


def test_anthropic_default_is_current():
    assert PRESETS["anthropic"].default_model == "claude-opus-5-5"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
