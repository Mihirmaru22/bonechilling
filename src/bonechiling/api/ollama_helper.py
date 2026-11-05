"""ollama_helper.py — let a non-technical user set up local AI from the app.

Checks whether Ollama is installed/running and can pull a vision model in the
background (streaming progress), so a doctor never opens a terminal.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Dict, List

import requests

RECOMMENDED_MODEL = "qwen2.5vl:3b"
INSTALL_URL = "https://ollama.com/download"
_OLLAMA_API = "http://localhost:11434/api/tags"

_pull: Dict = {"model": None, "active": False, "done": False, "error": None, "line": ""}
_lock = threading.Lock()


def status() -> Dict:
    models: List[str] = []
    running = False
    try:
        r = requests.get(_OLLAMA_API, timeout=2)
        if r.ok:
            running = True
            models = [m.get("name", "") for m in r.json().get("models", [])]
    except requests.RequestException:
        pass
    with _lock:
        pull = dict(_pull)
    return {
        "binary_present": bool(shutil.which("ollama")),
        "running": running,
        "models": models,
        "has_recommended": any(m.startswith(RECOMMENDED_MODEL.split(":")[0]) for m in models),
        "recommended_model": RECOMMENDED_MODEL,
        "install_url": INSTALL_URL,
        "pull": pull,
    }


def start_pull(model: str) -> Dict:
    if not shutil.which("ollama"):
        raise RuntimeError("Ollama is not installed. Download it first.")
    with _lock:
        if _pull["active"]:
            return dict(_pull)
        _pull.update(model=model, active=True, done=False, error=None, line="starting…")

    def _run():
        try:
            proc = subprocess.Popen(
                ["ollama", "pull", model],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            for line in proc.stdout or []:
                with _lock:
                    _pull["line"] = line.strip()
            proc.wait()
            err = None if proc.returncode == 0 else f"ollama exited {proc.returncode}"
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
        with _lock:
            _pull.update(active=False, done=True, error=err)

    threading.Thread(target=_run, daemon=True).start()
    with _lock:
        return dict(_pull)
