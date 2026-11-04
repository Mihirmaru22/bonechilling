"""settings.py — non-secret config (JSON) + secret API keys (OS keyring).

Keys entered in the frontend are stored in the OS credential store via
`keyring` (Windows Credential Manager / macOS Keychain / Secret Service),
NEVER in a plaintext file or the repo. Non-secret preferences (active provider,
model, thresholds) live in a JSON file under the per-user app-data dir.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import keyring
from keyring.errors import KeyringError

SERVICE = "bonechilling"

DEFAULTS: Dict[str, Any] = {
    "provider": "ollama",
    "model": None,              # None => the preset's default model
    "escalate_provider": None,  # optional cloud fallback
    "escalate_model": None,
    "ocr_backend": "tesseract",
    "concurrency": None,        # None => auto (serial local, parallel cloud)
    "cloud_notice_ack": False,  # has the doctor seen the "cloud sends data off-device" notice
}


def _root() -> Path:
    root = Path(os.environ.get("BONECHILLING_HOME", Path.home() / ".bonechilling"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_path() -> Path:
    env = os.environ.get("BONECHILLING_CONFIG")
    return Path(env) if env else _root() / "config.json"


# --------------------------------------------------------------------------- #
# Non-secret config
# --------------------------------------------------------------------------- #
def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_config()
    cfg.update({k: v for k, v in updates.items() if k in DEFAULTS})
    config_path().write_text(json.dumps(cfg, indent=2))
    return cfg


# --------------------------------------------------------------------------- #
# Secret API keys (keyring)
# --------------------------------------------------------------------------- #
def _entry(provider: str) -> str:
    return f"apikey:{provider}"


def set_api_key(provider: str, key: str) -> None:
    keyring.set_password(SERVICE, _entry(provider), key)


def get_api_key(provider: str) -> Optional[str]:
    try:
        return keyring.get_password(SERVICE, _entry(provider))
    except KeyringError:
        return None


def delete_api_key(provider: str) -> bool:
    try:
        keyring.delete_password(SERVICE, _entry(provider))
        return True
    except KeyringError:
        return False


def has_api_key(provider: str) -> bool:
    return bool(get_api_key(provider))
