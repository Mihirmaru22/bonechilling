"""openai_compat.py — one adapter for every OpenAI-compatible chat API.

Covers OpenAI, OpenRouter, Google Gemini (its OpenAI-compat endpoint), and
local Ollama (`/v1`). Uses `requests` directly — no provider SDK — so the
dependency surface and the Windows bundle stay small. The uniform JSON contract
is `core.schema.XrayFacts`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Union

import requests

from ..core.imaging import encode_jpeg_b64
from ..core.prompts import SYSTEM_PROMPT, USER_PROMPT
from ..core.schema import repair_and_validate
from .base import EngineConfig, EngineResult, _Timer


class OpenAICompatEngine:
    """Chat-completions engine with an image + JSON response format."""

    def __init__(self, config: EngineConfig):
        self.config = config

    # ------------------------------------------------------------------ #
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json", **self.config.extra_headers}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    def _endpoint(self) -> str:
        return self.config.base_url.rstrip("/") + "/chat/completions"

    def _payload(self, b64: str, mime: str) -> dict:
        return {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                },
            ],
            "temperature": self.config.temperature,
            "response_format": {"type": "json_object"},
        }

    # ------------------------------------------------------------------ #
    def analyze(self, image_path: Union[str, Path]) -> EngineResult:
        name = f"{self.config.provider}:{self.config.model}"
        try:
            b64, mime = encode_jpeg_b64(image_path)
        except Exception as exc:  # noqa: BLE001
            return EngineResult(facts=repair_and_validate(None), engine=name,
                                error=f"image encode failed: {exc}")

        payload = self._payload(b64, mime)
        last_err = None
        with _Timer() as t:
            for attempt in range(self.config.max_retries + 1):
                try:
                    resp = requests.post(self._endpoint(), headers=self._headers(),
                                         json=payload, timeout=self.config.timeout)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"  # retryable
                    elif resp.status_code >= 400:
                        # client error (bad key / bad request) — retrying won't help
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
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return json.dumps(body)[:500]

    def health_check(self) -> tuple[bool, str]:
        """Hit /models (OpenAI-compatible) to validate base_url + key."""
        url = self.config.base_url.rstrip("/") + "/models"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=15)
            if resp.status_code in (200, 401, 403):
                if resp.ok:
                    return True, "reachable"
                return False, f"auth rejected (HTTP {resp.status_code})"
            return False, f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            return False, str(exc)
