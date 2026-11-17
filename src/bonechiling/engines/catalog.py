"""catalog.py — curated vision-model choices for the model picker.

Picking from a list avoids the commonest setup failure: a model name typed with
a small mistake (``qwen2.5-vl`` vs ``qwen2.5vl``) that then fails on every film.

* Ollama: a fixed list of vision models under 15B parameters (pull tags as
  published in the Ollama library). Users can still type any other tag.
* Cloud providers: model IDs change often, so the live ``/models`` list from the
  provider (filtered to vision-capable models where the API says so) is the
  source of truth once a key is saved. The suggestions below are only shown
  until then, and are dropped if the live list shows they are not offered.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# The list itself lives in models.json so it can be maintained without code
# changes (see MAINTAINING_MODELS.md). status: current | deprecated | retired.
_DATA = json.loads((Path(__file__).with_name("models.json")).read_text(encoding="utf-8"))
OLLAMA_VISION: List[Dict[str, str]] = _DATA["ollama"]
CLOUD_SUGGESTED: Dict[str, List[Dict[str, str]]] = _DATA["cloud"]
CATALOG_UPDATED: str = _DATA.get("updated", "")


def catalog_entry(provider: str, model_id: str) -> Optional[Dict[str, str]]:
    items = OLLAMA_VISION if provider == "ollama" else CLOUD_SUGGESTED.get(provider, [])
    return next((m for m in items if m["id"] == model_id), None)


_NON_VISION_HINTS = ("embed", "embedding", "tts", "whisper", "transcribe", "audio", "realtime",
                     "moderation", "dall-e", "imagen", "image-", "aqa", "search", "davinci", "babbage")


def looks_vision_capable(provider: str, model_id: str) -> bool:
    """Heuristic for providers whose /models list has no modality field."""
    m = model_id.lower()
    if any(h in m for h in _NON_VISION_HINTS):
        return False
    if provider == "openai":
        return m.startswith(("gpt-4o", "gpt-4.1", "gpt-5", "chatgpt-4o", "o1", "o3", "o4"))
    if provider == "gemini":
        return "gemini" in m or "gemma-3" in m
    return True


def build_options(provider: str, live: Optional[Iterable[str]], installed: Iterable[str] = ()) -> List[Dict]:
    """Merge curated choices with what the provider/machine actually has.

    Each option: {id, label, note, size?, group, status}. ``status`` is one of
    ``installed`` / ``download`` (Ollama), ``available`` (seen in the live list)
    or ``suggested`` (not verified yet: no key saved / list unavailable).
    """
    opts: List[Dict] = []
    if provider == "ollama":
        have = {m for m in installed}
        base = {m.split(":")[0] + ":" + (m.split(":")[1] if ":" in m else "latest") for m in have}
        known = set()
        for item in OLLAMA_VISION:
            known.add(item["id"])
            is_in = item["id"] in have or item["id"] in base
            if item.get("status") == "retired" and not is_in:
                continue
            opts.append({**item, "lifecycle": item.get("status", "current"),
                         "group": "Vision models under 15B",
                         "status": "installed" if is_in else "download"})
        for m in sorted(have):
            if m not in known and m.replace(":latest", "") not in known:
                opts.append({"id": m, "label": m, "note": "Installed on this PC", "group": "Other installed models",
                             "status": "installed"})
        return opts

    suggested = CLOUD_SUGGESTED.get(provider, [])
    live_set = set(live or [])
    if live_set:
        for item in suggested:
            if item["id"] in live_set and item.get("status") != "retired":
                opts.append({**item, "lifecycle": item.get("status", "current"),
                             "group": "Recommended", "status": "available"})
        rec = {o["id"] for o in opts}
        for m in sorted(live_set):
            if m not in rec:
                cat = catalog_entry(provider, m) or {}
                opts.append({"id": m, "label": m, "note": cat.get("note", ""),
                             "lifecycle": cat.get("status", "current"), "replacement": cat.get("replacement"),
                             "group": "All vision models on your account", "status": "available"})
    else:
        for item in suggested:
            if item.get("status") == "retired":
                continue
            opts.append({**item, "lifecycle": item.get("status", "current"),
                         "group": "Suggested (verified once your key is saved)", "status": "suggested"})
    return opts


def saved_model_status(provider: str, model: Optional[str], live: Iterable[str], installed: Iterable[str] = ()) -> Dict:
    """Is the user's saved model still usable? Used for warnings in Settings and
    the pre-flight check before an ingest.

    state: ok | unknown (can't verify yet) | missing (provider no longer lists it,
    or not downloaded in Ollama) | deprecated | retired.
    """
    if not model:
        return {"state": "ok"}
    cat = catalog_entry(provider, model) or {}
    out = {"model": model, "replacement": cat.get("replacement")}
    if provider == "ollama":
        have = set(installed)
        if model not in have and (model + ":latest") not in have:
            return {**out, "state": "missing",
                    "message": f"'{model}' isn't downloaded in Ollama on this PC."}
    else:
        live_set = set(live or [])
        if not live_set:
            return {**out, "state": "unknown"}
        if model not in live_set:
            return {**out, "state": "missing",
                    "message": f"Your provider no longer offers '{model}' (it may have been retired or renamed)."}
    if cat.get("status") in ("deprecated", "retired"):
        word = "is being retired" if cat["status"] == "deprecated" else "has been retired"
        rep = f" Switch to {cat['replacement']}." if cat.get("replacement") else ""
        return {**out, "state": cat["status"], "message": f"'{model}' {word}.{rep}"}
    return {**out, "state": "ok"}

