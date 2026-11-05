"""Engine transport tests against a local mock HTTP server (no network)."""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bonechiling.engines.base import EngineConfig
from bonechiling.engines.openai_compat import OpenAICompatEngine

_OK = json.dumps({"choices": [{"message": {"content": json.dumps(
    {"image_type": "X-ray", "body_part": "wrist", "confidence": 0.8})}}]})

state = {"calls": 0, "mode": "ok"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _s(self, code, body):
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.end_headers(); self.wfile.write(body.encode())

    def do_POST(self):
        state["calls"] += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if state["mode"] == "ok":
            self._s(200, _OK)
        elif state["mode"] == "400":
            self._s(400, '{"error":"bad request"}')
        elif state["mode"] == "500":
            self._s(500, "boom")


_srv = HTTPServer(("127.0.0.1", 0), H)
_PORT = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()

IMG = next((Path(__file__).resolve().parents[1] / "test" / "1").glob("*.jpg"))


def _engine():
    return OpenAICompatEngine(EngineConfig(
        provider="openai", model="m", base_url=f"http://127.0.0.1:{_PORT}/v1",
        api_key="k", timeout=5, max_retries=2))


def test_success():
    state.update(calls=0, mode="ok")
    r = _engine().analyze(IMG)
    assert r.ok and r.facts.body_part == "wrist"
    assert state["calls"] == 1


def test_4xx_not_retried():
    state.update(calls=0, mode="400")
    r = _engine().analyze(IMG)
    assert not r.ok and "400" in r.error
    assert state["calls"] == 1, f"4xx must NOT be retried (was called {state['calls']}x)"


def test_5xx_retried():
    state.update(calls=0, mode="500")
    r = _engine().analyze(IMG)
    assert not r.ok
    assert state["calls"] == 3, f"5xx should retry to max (was {state['calls']})"


if __name__ == "__main__":
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name); n += 1
    print(f"\n{n} tests passed")
