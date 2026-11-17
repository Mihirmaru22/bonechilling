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

from typing import Dict, Iterable, List, Optional

# id, label, approx. download size, short note. Ordered by recommendation.
OLLAMA_VISION: List[Dict[str, str]] = [
    {"id": "qwen2.5vl:3b", "label": "Qwen2.5-VL 3B", "size": "3.2 GB", "note": "Recommended for laptops; reads film labels well"},
    {"id": "qwen2.5vl:7b", "label": "Qwen2.5-VL 7B", "size": "6.0 GB", "note": "More accurate; needs ~8 GB RAM/VRAM"},
    {"id": "qwen3-vl:2b", "label": "Qwen3-VL 2B", "size": "1.9 GB", "note": "Newest Qwen vision, smallest"},
    {"id": "qwen3-vl:4b", "label": "Qwen3-VL 4B", "size": "3.3 GB", "note": "Newest Qwen vision, balanced"},
    {"id": "qwen3-vl:8b", "label": "Qwen3-VL 8B", "size": "6.1 GB", "note": "Newest Qwen vision, most accurate under 15B"},
    {"id": "gemma4:e2b", "label": "Gemma 4 E2B", "size": "7.2 GB", "note": "Google, efficient 2B-effective"},
    {"id": "gemma4:e4b", "label": "Gemma 4 E4B", "size": "9.6 GB", "note": "Google, efficient 4B-effective"},
    {"id": "gemma3:4b", "label": "Gemma 3 4B", "size": "3.3 GB", "note": "Google, fast"},
    {"id": "gemma3:12b", "label": "Gemma 3 12B", "size": "8.1 GB", "note": "Google, strong general vision"},
    {"id": "ministral-3:3b", "label": "Ministral 3 3B", "size": "3.0 GB", "note": "Mistral, small"},
    {"id": "ministral-3:8b", "label": "Ministral 3 8B", "size": "6.0 GB", "note": "Mistral, balanced"},
    {"id": "ministral-3:14b", "label": "Ministral 3 14B", "size": "9.1 GB", "note": "Mistral, largest under 15B"},
    {"id": "llama3.2-vision:11b", "label": "Llama 3.2 Vision 11B", "size": "7.8 GB", "note": "Meta"},
    {"id": "minicpm-v:8b", "label": "MiniCPM-V 8B", "size": "5.5 GB", "note": "Good at reading text in images"},
    {"id": "granite3.2-vision:2b", "label": "Granite 3.2 Vision 2B", "size": "2.4 GB", "note": "IBM, document-focused"},
    {"id": "llava:7b", "label": "LLaVA 7B", "size": "4.7 GB", "note": "Classic, widely tested"},
    {"id": "llava:13b", "label": "LLaVA 13B", "size": "8.0 GB", "note": "Classic, larger"},
    {"id": "llava-llama3:8b", "label": "LLaVA-Llama3 8B", "size": "5.5 GB", "note": "LLaVA on Llama 3"},
    {"id": "llava-phi3:3.8b", "label": "LLaVA-Phi3 3.8B", "size": "2.9 GB", "note": "Small LLaVA"},
    {"id": "moondream:1.8b", "label": "Moondream 1.8B", "size": "1.7 GB", "note": "Tiny; fastest, least accurate"},
]

# Shown before a key is saved; replaced by the provider's live list afterwards.
CLOUD_SUGGESTED: Dict[str, List[Dict[str, str]]] = {
    "anthropic": [
        {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "Most capable Opus; default"},
        {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Fast and capable, lower cost"},
        {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "Cheapest and fastest"},
        {"id": "claude-fable-5-2", "label": "Claude Fable 5.2", "note": "Most capable, highest cost"},
        {"id": "claude-opus-5", "label": "Claude Opus 5", "note": "Previous Opus"},
        {"id": "claude-sonnet-5", "label": "Claude Sonnet 5", "note": "Previous Sonnet"},
    ],
    "openai": [
        {"id": "gpt-5", "label": "GPT-5", "note": ""},
        {"id": "gpt-5-mini", "label": "GPT-5 mini", "note": "Lower cost"},
        {"id": "gpt-4.1", "label": "GPT-4.1", "note": ""},
        {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini", "note": "Lower cost"},
        {"id": "gpt-4o", "label": "GPT-4o", "note": ""},
        {"id": "gpt-4o-mini", "label": "GPT-4o mini", "note": "Lowest cost"},
    ],
    "gemini": [
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "note": "Fast, good value"},
        {"id": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite", "note": "Cheapest"},
        {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro", "note": "Most accurate"},
        {"id": "gemini-2.0-flash", "label": "Gemini 2.0 Flash", "note": "Older"},
    ],
    "openrouter": [
        {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash", "note": "Fast, good value"},
        {"id": "google/gemini-2.0-flash-001", "label": "Gemini 2.0 Flash", "note": ""},
        {"id": "anthropic/claude-sonnet-4.5", "label": "Claude Sonnet 4.5", "note": ""},
        {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "note": ""},
        {"id": "qwen/qwen2.5-vl-72b-instruct", "label": "Qwen2.5-VL 72B", "note": ""},
        {"id": "meta-llama/llama-3.2-11b-vision-instruct", "label": "Llama 3.2 11B Vision", "note": ""},
    ],
}

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
            opts.append({**item, "group": "Vision models under 15B",
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
            if item["id"] in live_set:
                opts.append({**item, "group": "Recommended", "status": "available"})
        rec = {o["id"] for o in opts}
        for m in sorted(live_set):
            if m not in rec:
                opts.append({"id": m, "label": m, "note": "", "group": "All vision models on your account",
                             "status": "available"})
    else:
        for item in suggested:
            opts.append({**item, "group": "Suggested (verified once your key is saved)", "status": "suggested"})
    return opts
