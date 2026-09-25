"""pipeline.py — the glue. Processes a folder of films."""
import sys
from pathlib import Path

from ocr import ocr_lines
from normalize import normalize
from vision import analyze
from db import connect, save_record

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

def process_folder(folder_path):
    folder = Path(folder_path)
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        return

    conn = connect()
    images = [f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTS]
    print(f"Found {len(images)} images in {folder.name}")

    for img_path in images:
        print(f"\n--- Processing {img_path.name} ---")

        # 1. Read text
        lines = ocr_lines(img_path)
        print(f"OCR found {len(lines)} lines.")

        # 2. Extract fields
        norm = normalize(lines)
        print(f"Normalized name: {norm['name']}")

        # 3. Ask the vision model
        vision = analyze(img_path)
        print(f"Vision impression: {vision['impression']}")

        # 4. Save to DB
        record = {
            "file_path": str(img_path.resolve()),
            "raw_ocr": lines,
            "norm": norm,
            "vision": vision,
        }
        pid = save_record(conn, record)
        print(f"Saved to DB! Patient ID: {pid}")

if __name__ == "__main__":
    # SELF-TEST: python pipeline.py data
    if len(sys.argv) != 2:
        print("usage: python pipeline.py <folder>")
        sys.exit(1)
    process_folder(sys.argv[1])