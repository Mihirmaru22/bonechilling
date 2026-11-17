"""registry.py — provider presets and the engine factory.

The UI shows these presets (friendly name -> base_url + recommended model).
The user picks one and pastes a key; `build_engine` returns the right adapter.
Model lists are fetched live from the provider where possible rather than
hardcoded, so new models work without a code change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import requests

from .anthropic_engine import ANTHROPIC_VERSION, AnthropicEngine
from .base import EngineConfig, VisionEngine
from .catalog import looks_vision_capable
from .openai_compat import OpenAICompatEngine


@dataclass(frozen=True)
class ProviderPreset:
    key: str                 # internal id
    label: str               # shown in UI
    base_url: str
    default_model: str
    needs_key: bool
    adapter: str             # "openai_compat" | "anthropic"
    notes: str = ""


PRESETS: dict[str, ProviderPreset] = {
    "ollama": ProviderPreset(
        "ollama", "Local (Ollama)", "http://localhost:11434/v1",
        "qwen2.5vl:3b", needs_key=False, adapter="openai_compat",
        notes="Runs on this PC. Private but slow on CPU-only laptops.",
    ),
    "openrouter": ProviderPreset(
        "openrouter", "OpenRouter", "https://openrouter.ai/api/v1",
        "google/gemini-2.0-flash-001", needs_key=True, adapter="openai_compat",
        notes="One key, many models. Good accurate default for weak laptops.",
    ),
    "openai": ProviderPreset(
        "openai", "OpenAI (GPT)", "https://api.openai.com/v1",
        "gpt-4o-mini", needs_key=True, adapter="openai_compat",
    ),
    "gemini": ProviderPreset(
        "gemini", "Google (Gemini)",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.0-flash", needs_key=True, adapter="openai_compat",
    ),
    "anthropic": ProviderPreset(
        "anthropic", "Anthropic (Claude)", "https://api.anthropic.com",
        "claude-opus-5-5", needs_key=True, adapter="anthropic",
    ),
}


def config_from_preset(
    provider: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    **overrides,
) -> EngineConfig:
    preset = PRESETS.get(provider)
    if preset is None:
        raise ValueError(f"unknown provider '{provider}'. Known: {', '.join(PRESETS)}")
    extra_headers = dict(overrides.pop("extra_headers", {}))
    if provider == "openrouter":
        # OpenRouter likes these for attribution/routing; harmless elsewhere.
        extra_headers.setdefault("HTTP-Referer", "https://bonechilling.local")
        extra_headers.setdefault("X-Title", "BoneChilling")
    # Local Ollama defaults to a long timeout (cold model loads).
    overrides.setdefault("timeout", 600.0 if provider == "ollama" else 120.0)
    return EngineConfig(
        provider=provider,
        model=model or preset.default_model,
        base_url=preset.base_url,
        api_key=api_key,
        extra_headers=extra_headers,
        **overrides,
    )


def build_engine(config: EngineConfig) -> VisionEngine:
    preset = PRESETS.get(config.provider)
    adapter = preset.adapter if preset else "openai_compat"
    if adapter == "anthropic":
        return AnthropicEngine(config)
    return OpenAICompatEngine(config)


def list_models(config: EngineConfig, vision_only: bool = True) -> List[str]:
    """Best-effort live model list from the provider (empty list on any error).

    With ``vision_only`` the list is narrowed to models that accept images:
    OpenRouter reports input modalities; Anthropic models all take images;
    OpenAI/Gemini have no modality field, so a name heuristic is used.
    """
    preset = PRESETS.get(config.provider)
    try:
        if preset and preset.adapter == "anthropic":
            ids: List[str] = []
            url = config.base_url.rstrip("/") + "/v1/models"
            headers = {"x-api-key": config.api_key or "", "anthropic-version": ANTHROPIC_VERSION}
            params = {"limit": 100}
            for _ in range(10):  # paginate
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                resp.raise_for_status()
                body = resp.json()
                ids += [m.get("id", "") for m in body.get("data", []) if m.get("id")]
                if not body.get("has_more"):
                    break
                params["after_id"] = body.get("last_id")
            return sorted(set(ids))

        url = config.base_url.rstrip("/") + "/models"
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except (requests.RequestException, ValueError, AttributeError):
        return []

    out = []
    for m in data:
        mid = (m.get("id") or "").removeprefix("models/")
        if not mid:
            continue
        if vision_only:
            mods = ((m.get("architecture") or {}).get("input_modalities"))
            if mods is not None:
                if "image" not in mods:
                    continue
            elif not looks_vision_capable(config.provider, mid):
                continue
        out.append(mid)
    return sorted(set(out))
