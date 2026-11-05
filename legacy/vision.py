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

from PIL import Image, ImageStat
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5vl:3b"          # switch to :7b if you have 16GB+ RAM

SYSTEM_PROMPT = (
    "You are an objective radiographic fact extractor for orthopedic clinical records. "
    "DO NOT diagnose diseases or speculate on causes. State strictly verifiable facts visible in the image. "
    "Physicians need objective facts at a glance before inspecting the film. Return valid JSON only."
)

USER_PROMPT = """Extract strictly verifiable radiographic facts from this X-ray film for the physician.
Do NOT give clinical diagnoses or speculative interpretations. Return verifiable facts only.

If this image is NOT a medical X-ray (e.g. document, prescription, clinical photo of wound/person, ID card), set:
{"image_type": "Non-X-ray", "body_part": null, "impression": "Non-X-ray image"}

Otherwise, return JSON with exactly these fields:
{"image_type": "X-ray", "body_part": null, "laterality": null, "views": [],
 "hardware": [], "visible_findings": [], "impression": null,
 "image_quality": null, "urgency": null, "confidence": 0.0, "limitations": []}

Requirements:
1. hardware: List specific implants, locations, counts, and integrity (e.g. 'Olecranon plate with 4 cortical screws (intact)', '2 K-wires at medial condyle (intact)').
2. visible_findings: Strictly observable facts on bone alignment, cortical continuity, and joint spaces.
3. impression: State the verifiable radiographic facts so the physician knows the exact status before looking at the film:
   - Anatomy, laterality, and specific projections visible.
   - Exact surgical hardware present, anatomical location, count, and integrity (no loosening/displacement/breakage).
   - Bone alignment, cortical continuity, and reduction status.
   - Articular joint space congruity.
   - Absence of acute hardware failure or dislocation."""

EMPTY = {"is_xray": False, "image_type": None, "body_part": None, "laterality": None,
         "views": [], "hardware": [], "visible_findings": [],
         "impression": None, "image_quality": None, "urgency": None,
         "confidence": 0.0, "limitations": []}


def is_likely_xray(image_path):
    """Fast (0.005s) check to filter out non-X-rays (prescriptions, clinical wound photos, documents)."""
    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            stat = ImageStat.Stat(rgb)
            r, g, b = stat.mean
            # Color disparity: X-rays are monochromatic/grayscale
            color_diff = (abs(r - g) + abs(g - b) + abs(b - r)) / 3.0
            if color_diff > 28:
                return False  # Color photo (wound, skin, etc.)

            gray = img.convert("L")
            hist = gray.histogram()
            total = sum(hist)
            if total == 0:
                return False
            # Check white paper ratio (documents/prescriptions have mostly white pixels > 215)
            white_ratio = sum(hist[215:]) / total
            if white_ratio > 0.70:
                return False  # White paper document / report

            dark_ratio = sum(hist[:70]) / total
            if dark_ratio < 0.08 and white_ratio > 0.50:
                return False

            return True
    except Exception:
        return False


def analyze(image_path, model=MODEL, max_size=1280):
    # 1. Fast pre-filter: Skip non-X-rays instantly without burning CPU/GPU
    if not is_likely_xray(image_path):
        out = dict(EMPTY)
        out["is_xray"] = False
        out["image_type"] = "Non-X-ray"
        out["impression"] = "Skipped: Non-X-ray image (document or clinical photo)."
        return out

    # 2. Downscale oversized photos to prevent Ollama context explosion and timeouts
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
    # Bumped to 600 seconds for cold starts
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

    image_type = str(out.get("image_type") or "").strip().lower()
    is_xray = ("x-ray" in image_type or "xray" in image_type or "radiograph" in image_type)
    out["is_xray"] = is_xray and (out.get("body_part") is not None)
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