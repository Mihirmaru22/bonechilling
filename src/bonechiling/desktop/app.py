"""app.py — the desktop shell: a pywebview window over the local FastAPI server.

Starts the API in-process on a random localhost port with a random per-launch
token, waits for it to come up, then opens a native window pointed at the SPA
with ?token=... A small JS bridge exposes a native folder picker (browser
drag-and-drop can't give real disk paths).

On Windows, pywebview renders via Microsoft Edge WebView2 (bundle the Evergreen
bootstrapper in the installer for older PCs).
"""
from __future__ import annotations

import secrets
import socket
import threading
import time
from pathlib import Path
from typing import List, Optional

from ..api.server import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_health(port: int, timeout: float = 20.0) -> bool:
    import requests

    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=1).ok:
                return True
        except requests.RequestException:
            time.sleep(0.15)
    return False


class Bridge:
    """Exposed to the page as window.pywebview.api."""

    def pick_folders(self) -> List[str]:
        import webview

        win = webview.windows[0] if webview.windows else None
        if win is None:
            return []
        result = win.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=True)
        return list(result) if result else []


def run(port: Optional[int] = None, db_path: Optional[Path] = None) -> int:
    import uvicorn
    import webview

    port = port or _free_port()
    token = secrets.token_urlsafe(24)
    app = create_app(token=token, db_path=db_path)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()

    if not _wait_health(port):
        print("ERROR: backend did not start in time.")
        return 1

    webview.create_window(
        "BoneChilling — Orthopedic X-ray Reader",
        f"http://127.0.0.1:{port}/?token={token}",
        width=1280, height=820, min_size=(960, 640),
        js_api=Bridge(),
    )
    webview.start()
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
