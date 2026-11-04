# BoneChilling 🦴
### Bulk Orthopedic X-ray Reader — local or cloud AI, for clinicians

**BoneChilling** reads a folder of patient X-ray studies in bulk and extracts
objective radiographic facts (anatomy, projections, surgical hardware, alignment)
plus patient demographics, into a reviewable worklist and an Excel export. It
runs against a **local model (Ollama)** for privacy or any **cloud API**
(OpenRouter, OpenAI, Gemini, Anthropic) for accuracy — the API key is entered
from the app, no code editing. Objective facts only; every result is for a
qualified physician to verify.

> **v2 rewrite.** The app is now the `bonechiling` Python package under
> [`src/bonechiling/`](src/bonechiling/). The original flat scripts + PySide6 app
> are archived in [`legacy/`](legacy/).

---

## Architecture

```
Folder(s) of patient studies
   └── per image:  sha256 (idempotent)  →  prefilter / DICOM detect
                   →  find & straighten film (OpenCV)  →  OCR label (best of raw/crop)
                   →  Vision model (local or cloud) → objective facts (JSON schema)
                   →  OCR-vs-model cross-check  →  escalate to cloud on conflict
                   →  SQLite (folder = patient, full provenance)
   →  cross-projection hardware reconcile  →  Worklist / Review / Excel export
```

- **`core/`** — schema (typed contract), prompts, prefilter, film detection,
  OCR, normalize, cross-check, DICOM, reconcile.
- **`engines/`** — one OpenAI-compatible adapter (OpenAI/OpenRouter/Gemini/Ollama)
  + a native Anthropic adapter; registry of provider presets.
- **`pipeline/`** — headless batch runner (idempotent, concurrent for cloud).
- **`data/`** — SQLite + migrations, keyring-backed settings, Excel export.
- **`api/`** — FastAPI backend (token-authed) + background jobs + progress WebSocket.
- **`webui/`** — no-build static SPA (worklist, patient review, ingest, settings).
- **`desktop/`** — pywebview window wrapping the API + SPA as one app.
- **`eval/`** — accuracy harness scoring extraction against labels.

## Prerequisites

- **Python 3.9+**
- **Tesseract** (optional, for label OCR on photos) — `brew install tesseract`
  / UB-Mannheim installer on Windows (auto-detected).
- For local AI: **[Ollama](https://ollama.com)** running a vision model, e.g.
  `ollama pull qwen2.5vl:3b`. For cloud AI: an API key from your provider.

## Install & run

```bash
uv sync    # or: pip install -e .
```

Launch the desktop app (starts the backend + opens the window):

```bash
uv run bonechilling app
```

Or run headless:

```bash
uv run bonechilling serve                 # API only (127.0.0.1)
uv run bonechilling ingest /path/to/batch --provider ollama
uv run bonechilling ingest /path/to/batch --provider openrouter --model google/gemini-2.0-flash-001
uv run bonechilling eval eval/labels.json --provider ollama
uv run bonechilling engine-test --provider openai
```

Cloud keys come from `--api-key`, the provider env var (e.g. `OPENAI_API_KEY`),
or — in the app — the **Settings** screen, which stores them in your OS
credential store (never in a file).

## Accuracy approach

- Strict JSON schema with tolerant repair; one bounded re-ask on failure.
- Film detection + straighten so the model/OCR see the film, not the whole photo.
- OCR and the vision model both read the label; **agreement = verified,
  disagreement = flagged**, and disagreement/validation-failure **escalates** a
  single image from local to cloud (never self-reported confidence).
- `eval/harness.py` measures per-field accuracy vs labels so changes are proven.
  Sample labels in `eval/labels.json` are a **bootstrap baseline, not
  human-verified** — a doctor's verified reviews should replace them.

## Data & privacy

- Patient identity is the **folder** (not the OCR'd name); images are
  deduplicated by SHA-256, so re-dropping a folder is safe.
- The DB lives outside the repo (`~/.bonechilling`, or `$BONECHILLING_DB`).
- Cloud providers send images off-device; the app shows a one-time notice.
  DICOM is read tags-first (demographics from tags, no OCR needed).

## Tests

```bash
for t in tests/test_*.py; do python "$t"; done
```

## Medical disclaimer

BoneChilling is an assistive workflow tool. Extracted facts and AI output must
always be verified by a qualified physician or radiologist.
