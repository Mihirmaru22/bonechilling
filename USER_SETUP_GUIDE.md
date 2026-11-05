# BoneChilling — Quick Start (Windows)

Welcome! BoneChilling reads your patient X-ray folders and extracts the key facts
for you to review. Two ways to run the AI — pick either.

---

## Install the app
1. Run **`BoneChilling-Setup.exe`** and follow the prompts.
2. Launch **BoneChilling** from the Start menu.

---

## Choose how the AI runs (first launch → Settings)

### Option A — Cloud (easiest, most accurate)
1. Open **Settings**.
2. Pick a provider (e.g. **OpenRouter**, OpenAI, Gemini, Anthropic).
3. Paste your **API key** and click **Test & Save**. The key is stored securely
   on your PC (Windows Credential Manager) — never in a file.

> Cloud providers send the X-ray images to that provider for analysis. Settings
> shows a reminder. Use Option B to keep everything on your PC.

### Option B — Local (private, no key, no internet)
1. In **Settings → Local AI (Ollama)**, click **Download Ollama** if it isn't
   installed, run that installer, then come back.
2. Click **Download recommended model** and wait for it to finish (one time).
3. In **Settings**, choose provider **Local (Ollama)**.

*Local AI is private but slower on laptops without a graphics card.*

---

## Use it
1. Go to **Ingest**, click **Choose folder…**, and select a patient folder or a
   batch folder containing many patient subfolders.
2. Click **Start analysis** and watch the progress.
3. Open the **Worklist**, click a patient to review the facts, verify or add
   notes, then use **📊 Download Excel** to export everything.

*Optional:* install **Tesseract OCR** (UB-Mannheim installer) to read patient
name/date labels printed on film photos — the app auto-detects it.

---

**Reminder:** BoneChilling is an assistant. Always verify every result yourself.
