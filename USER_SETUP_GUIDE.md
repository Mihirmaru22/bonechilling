# BoneChilling — Quick User Guide (Windows)

Welcome to **BoneChilling**! This guide will help you run the application in 2 simple steps.

---

### Step 1: Install Ollama (AI Engine)
BoneChilling runs an intelligent local vision AI model directly on your machine.

1. Download and run the 1-click Windows installer from **[ollama.com/download](https://ollama.com/download)** (`OllamaSetup.exe`).
2. Once installed, open your **Command Prompt** (press `Win + R`, type `cmd`, and press Enter).
3. Copy and paste this command, then press Enter:
   ```cmd
   ollama run qwen2.5vl:3b
   ```
   *(This downloads and starts the radiology vision model. You only need to download it once!)*

---

### Step 2: Run BoneChilling
1. Double-click **`BoneChilling.exe`**.
2. Drag and drop any folder containing patient X-ray films directly onto the window (or click **+ Ingest Folder**).
3. The app will automatically pre-filter, read patient labels, extract objective radiographic facts, and reconcile orthopedic hardware across views.
4. Click **📊 Download Excel Sheet** anytime to export verified studies with clickable links.

---

### Optional: Tesseract OCR (For Patient Label Band Reading)
If your hospital films have printed patient name/date bands at the bottom:
1. Download the Windows installer from: **[UB-Mannheim Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)**.
2. Install it with default settings (`C:\Program Files\Tesseract-OCR`).
3. BoneChilling will auto-detect it on launch.
