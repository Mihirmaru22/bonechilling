"""base.py — the vision engine interface and shared result type.

Every provider (local or cloud) is a VisionEngine. The pipeline only ever sees
`EngineResult`, so swapping providers or adding escalation/self-consistency is a
pipeline concern, not a per-provider one.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol, Union, runtime_checkable

from ..core.schema import XrayFacts


@dataclass
class EngineConfig:
    """Everything needed to talk to one provider+model."""

    provider: str                      # 'openai' | 'openrouter' | 'ollama' | 'gemini' | 'anthropic'
    model: str
    base_url: str
    api_key: Optional[str] = None
    timeout: float = 120.0
    max_retries: int = 2
    temperature: float = 0.0
    extra_headers: dict = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.provider == "ollama"


@dataclass
class EngineResult:
    """Outcome of one analyze() call."""

    facts: XrayFacts
    engine: str                        # "provider:model"
    latency_ms: int = 0
    raw_response: Optional[str] = None
    error: Optional[str] = None
    cost_usd: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@runtime_checkable
class VisionEngine(Protocol):
    config: EngineConfig

    def analyze(self, image_path: Union[str, Path]) -> EngineResult: ...

    def health_check(self) -> tuple[bool, str]: ...


class _Timer:
    def __enter__(self):
        self._t = time.perf_counter()
        self.ms = 0
        return self

    def elapsed_ms(self) -> int:
        """Live elapsed time — valid inside the with-block, unlike .ms."""
        return int((time.perf_counter() - self._t) * 1000)

    def __exit__(self, *exc):
        self.ms = self.elapsed_ms()


_MODEL_GONE_HINTS = ("model_not_found", "model not found", "does not exist", "not found for api version",
                     "no such model", "decommission", "deprecated", "retired", "is not supported",
                     "unknown model", "invalid model", "no endpoints found")


def explain_http_error(status: int, body: str, model: str) -> str:
    """Turn a provider error into something a clinician can act on.

    The common case worth special wording is a model the provider has retired
    or renamed: the fix is to pick another model and retry the failed films."""
    text = (body or "")[:300]
    low = text.lower()
    if status in (400, 404, 410) and "model" in low and any(h in low for h in _MODEL_GONE_HINTS):
        return (f"Model '{model}' isn't available from this provider any more (retired or renamed). "
                f"Pick another model in Settings, then use 'Retry failed films'. [HTTP {status}: {text[:160]}]")
    if status in (401, 403):
        return f"The provider rejected the API key (HTTP {status}). Check the key in Settings."
    if status == 429:
        return f"Rate limit or quota reached at the provider (HTTP 429). Try again later. {text[:120]}"
    return f"HTTP {status}: {text[:200]}"

