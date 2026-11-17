"""check_models.py — verify the curated model list still matches reality.

Run monthly by .github/workflows/check-models.yml (and on any change to the
list). Exits non-zero when a model marked "current" no longer exists, so the
workflow fails and GitHub emails the repository owner.

* Ollama: every tag is checked against the public registry (no key needed).
* OpenRouter: its public /models list is checked (no key needed).
* Anthropic / OpenAI / Gemini: checked only when an API key is provided as an
  environment variable (repository secrets), otherwise skipped.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

DATA = json.loads((Path(__file__).resolve().parents[1] / "src/bonechiling/engines/models.json").read_text())
TIMEOUT = 20


def ollama_exists(tag: str) -> bool:
    name, _, ver = tag.partition(":")
    url = f"https://registry.ollama.ai/v2/library/{name}/manifests/{ver or 'latest'}"
    r = requests.get(url, timeout=TIMEOUT, headers={
        "Accept": "application/vnd.docker.distribution.manifest.v2+json"})
    if r.status_code in (200, 404):
        return r.status_code == 200
    r.raise_for_status()
    return False


def live_ids(provider: str):
    """Return the provider's model IDs, or None when it can't be checked here."""
    if provider == "openrouter":
        r = requests.get("https://openrouter.ai/api/v1/models", timeout=TIMEOUT)
        r.raise_for_status()
        return {m["id"] for m in r.json()["data"]}
    if provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
        ids, params = set(), {"limit": 100}
        while True:
            r = requests.get("https://api.anthropic.com/v1/models", params=params, timeout=TIMEOUT,
                             headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
            r.raise_for_status()
            body = r.json()
            ids |= {m["id"] for m in body["data"]}
            if not body.get("has_more"):
                return ids
            params["after_id"] = body["last_id"]
    if provider == "openai" and os.getenv("OPENAI_API_KEY"):
        r = requests.get("https://api.openai.com/v1/models", timeout=TIMEOUT,
                         headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        r.raise_for_status()
        return {m["id"] for m in r.json()["data"]}
    if provider == "gemini" and os.getenv("GEMINI_API_KEY"):
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/openai/models", timeout=TIMEOUT,
                         headers={"Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"})
        r.raise_for_status()
        return {m["id"].removeprefix("models/") for m in r.json()["data"]}
    return None


def main() -> int:
    rows, problems = [], 0
    for m in DATA["ollama"]:
        try:
            ok = ollama_exists(m["id"])
        except requests.RequestException as exc:
            rows.append(("ollama", m["id"], m.get("status", "current"), f"check failed: {exc}"))
            continue
        status = m.get("status", "current")
        verdict = "ok" if ok else "MISSING from Ollama library"
        if not ok and status == "current":
            problems += 1
        rows.append(("ollama", m["id"], status, verdict))

    for provider, items in DATA["cloud"].items():
        try:
            live = live_ids(provider)
        except requests.RequestException as exc:
            rows.append((provider, "*", "", f"check failed: {exc}"))
            continue
        for m in items:
            status = m.get("status", "current")
            if live is None:
                rows.append((provider, m["id"], status, "skipped (no API key secret)"))
                continue
            ok = m["id"] in live
            if not ok and status != "retired":
                problems += 1
            rows.append((provider, m["id"], status, "ok" if ok else "NOT OFFERED by provider"))

    lines = [f"## Model catalog check (list updated {DATA.get('updated', '?')})", "",
             "| Provider | Model | Status in list | Result |", "|---|---|---|---|"]
    lines += [f"| {p} | `{i}` | {s} | {v} |" for p, i, s, v in rows]
    lines += ["", f"**{problems} problem(s).**" + (" Edit `src/bonechiling/engines/models.json`: mark the model "
              "`deprecated`/`retired`, set a `replacement`, or remove it. See MAINTAINING_MODELS.md." if problems else "")]
    report = "\n".join(lines)
    print(report)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
