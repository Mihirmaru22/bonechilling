"""anthropic_engine.py — native Claude Messages API adapter (via requests).

Anthropic's API isn't OpenAI-shaped (different auth header, image block format,
and no response_format), so it gets its own small adapter. Claude can also be
reached through OpenRouter with the OpenAI-compat adapter; this is the direct
path for users who paste an Anthropic key.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Union

import requests

from ..core.imaging import encode_jpeg_b64
from ..core.prompts import SYSTEM_PROMPT, USER_PROMPT
from ..core.schema import repair_and_validate
from .base import EngineConfig, EngineResult, _Timer

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicEngine:
    def __init__(self, config: EngineConfig):
        self.config = config

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.config.api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            **self.config.extra_headers,
        }

    def analyze(self, image_path: Union[str, Path]) -> EngineResult:
        name = f"{self.config.provider}:{self.config.model}"
        try:
            b64, mime = encode_jpeg_b64(image_path)
        except Exception as exc:  # noqa: BLE001
            return EngineResult(facts=repair_and_validate(None), engine=name,
                                error=f"image encode failed: {exc}")

        payload = {
            "model": self.config.model,
            "max_tokens": 2048,   # radiographic JSON can be long; avoid truncation
            "temperature": self.config.temperature,
            "system": SYSTEM_PROMPT + " Respond with only the JSON object.",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text", "text": USER_PROMPT},
                ],
            }],
        }
        url = self.config.base_url.rstrip("/") + "/v1/messages"
        last_err = None
        with _Timer() as t:
            for attempt in range(self.config.max_retries + 1):
                try:
                    resp = requests.post(url, headers=self._headers(), json=payload,
                                         timeout=self.config.timeout)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"  # retryable
                    elif resp.status_code >= 400:
                        return EngineResult(facts=repair_and_validate(None), engine=name,
                                            latency_ms=t.elapsed_ms(),
                                            error=f"HTTP {resp.status_code}: {resp.text[:200]}")
                    else:
                        content = self._extract_content(resp.json())
                        return EngineResult(facts=repair_and_validate(content), engine=name,
                                            latency_ms=t.elapsed_ms(), raw_response=content)
                except requests.RequestException as exc:
                    last_err = str(exc)
                if attempt < self.config.max_retries:
                    time.sleep(min(2 ** attempt, 8))
        return EngineResult(facts=repair_and_validate(None), engine=name,
                            latency_ms=t.elapsed_ms(), error=last_err or "unknown error")

    @staticmethod
    def _extract_content(body: dict) -> str:
        try:
            blocks = body.get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except (AttributeError, TypeError):
            return ""

    def health_check(self) -> tuple[bool, str]:
        # A tiny messages call is the cheapest reliable key check.
        url = self.config.base_url.rstrip("/") + "/v1/messages"
        try:
            resp = requests.post(url, headers=self._headers(),
                                 json={"model": self.config.model, "max_tokens": 1,
                                       "messages": [{"role": "user", "content": "hi"}]},
                                 timeout=15)
            if resp.ok:
                return True, "reachable"
            if resp.status_code in (401, 403):
                return False, "auth rejected"
            return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
        except requests.RequestException as exc:
            return False, str(exc)
