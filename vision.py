"""vision.py — asks a local vision model what is visible in the X-ray."""
import base64
import io
import json
import sys
import warnings
from pathlib import Path

# 1. Hide the harmless Mac SSL warning before urllib3 loads
warnings.filterwarnings("ignore")
import urllib3
urllib3.disable_warnings()

from PIL import Image
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5vl:3b"          # switch to :7b if you have 16GB+ RAM

SYSTEM_PROMPT = (
    "You are a radiology image description assistant for record keeping. "
    "Describe only what is visible. Never give a final diagnosis. "
    "Never invent findings. If unsure, say uncertain and lower confidence. "
    "Return JSON only."
)

USER_PROMPT = """Analyze this X-ray photo for record keeping.
Return JSON only with exactly these fields:
{"image_type": null, "body_part": null, "laterality": null, "views": [],
 "hardware": [], "visible_findings": [], "impression": null,
 "image_quality": null, "urgency": null, "confidence": 0.0, "limitations": []}
Describe hardware explicitly (plate, screws, k-wires, nail, fixator, wire).
If the image looks post-operative, say so in impression."""

EMPTY = {"image_type": None, "body_part": None, "laterality": None,
         "views": [], "hardware": [], "visible_findings": [],
         "impression": None, "image_quality": None, "urgency": None,
         "confidence": 0.0, "limitations": []}


def analyze(image_path, model=MODEL, max_size=1280):
    # Downscale oversized photos to prevent Ollama context explosion and timeouts
    with Image.open(image_path) as img:
        if max(img.size) > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64 = base64.b64encode(buf.getvalue()).decode()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT, "images": [b64]},
        ],
        "format": "json",
        "options": {"temperature": 0},
        "stream": False,
    }
    # 2. Bumped to 600 seconds (10 minutes) for cold starts
    resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
    resp.raise_for_status()
    content = resp.json()["message"]["content"]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        out = dict(EMPTY)
        out["limitations"] = ["model returned non-JSON output"]
        out["impression"] = content[:500]
        return out

    out = dict(EMPTY)
    for key in EMPTY:
        out[key] = parsed.get(key, EMPTY[key])
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python vision.py <image>")
        sys.exit(1)
    try:
        print(json.dumps(analyze(sys.argv[1]), indent=2))
    except requests.ConnectionError:
        print("ERROR: cannot reach Ollama at", OLLAMA_URL)
        print("start it with:  ollama serve")
        sys.exit(1)