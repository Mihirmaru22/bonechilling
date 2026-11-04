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

from .anthropic_engine import AnthropicEngine
from .base import EngineConfig, VisionEngine
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
        "claude-3-5-sonnet-latest", needs_key=True, adapter="anthropic",
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


def list_models(config: EngineConfig) -> List[str]:
    """Best-effort live model list from an OpenAI-compatible /models endpoint.

    Returns [] for Anthropic (no public list endpoint) or on any error; the UI
    then falls back to the preset's default model.
    """
    if PRESETS.get(config.provider) and PRESETS[config.provider].adapter == "anthropic":
        return []
    url = config.base_url.rstrip("/") + "/models"
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return sorted(m.get("id", "") for m in data if m.get("id"))
    except (requests.RequestException, ValueError, AttributeError):
        return []
