"""pipeline.py — the glue. Processes a folder of films."""
import sys
from pathlib import Path

from ocr import ocr_lines
from normalize import normalize
from vision import analyze, is_likely_xray
from db import (
    connect, save_record, get_or_create_patient,
    reconcile_patient_study_hardware, reconcile_hardware_cross_projections
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

def get_patient_folders(root_dir):
    root = Path(root_dir)
    if not root.is_dir():
        return []
    subdirs = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    patient_dirs = [d for d in subdirs if any(f.suffix.lower() in IMAGE_EXTS for f in d.iterdir() if f.is_file())]
    if patient_dirs:
        return sorted(patient_dirs)
    if any(f.suffix.lower() in IMAGE_EXTS for f in root.iterdir() if f.is_file()):
        return [root]
    return []

def process_folder(folder_path):
    patient_folders = get_patient_folders(folder_path)
    if not patient_folders:
        print(f"No patient images found in {folder_path}")
        return

    conn = connect()
    total_processed = 0

    for p_folder in patient_folders:
        imgs = [f for f in p_folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        if not imgs:
            continue

        print(f"\n=== Patient Folder: {p_folder.name} ({len(imgs)} files) ===")
        folder_patient_id = None

        for img_path in imgs:
            # 1. Fast pre-filter: silently skip non-X-rays
            if not is_likely_xray(img_path):
                continue

            print(f"--- Processing X-ray: {img_path.name} ---")
            lines = ocr_lines(img_path)
            norm = normalize(lines)
            vision = analyze(img_path)

            # 2. Vision model check: silently skip non-X-rays
            if not vision.get("is_xray", False):
                continue

            if folder_patient_id is None:
                patient_name = norm.get('name') or p_folder.name
                folder_patient_id = get_or_create_patient(
                    conn,
                    name=patient_name,
                    patient_id=norm.get('accession_or_id'),
                    age=norm.get('age'),
                    sex=norm.get('sex')
                )

            record = {
                "file_path": str(img_path.resolve()),
                "file_name": img_path.name,
                "folder_name": p_folder.name,
                "raw_ocr": lines,
                "norm": norm,
                "vision": vision,
                "patient_id": folder_patient_id,
            }
            save_record(conn, record, patient_id=folder_patient_id)
            total_processed += 1
            print(f"Saved X-ray to DB! Patient: {norm.get('name') or p_folder.name} (ID: {folder_patient_id})")

        # Cross-projection hardware reconciliation across all views for this patient
        if folder_patient_id:
            reconciled = reconcile_patient_study_hardware(conn, folder_patient_id)
            print(f"\n[Cross-Projection Reconciled Hardware for {p_folder.name}]:")
            for h in reconciled:
                print(f"  • {h}")

    print(f"\nFinished. Processed {total_processed} X-rays.")

if __name__ == "__main__":
    # SELF-TEST: python pipeline.py data
    if len(sys.argv) != 2:
        print("usage: python pipeline.py <folder>")
        sys.exit(1)
    process_folder(sys.argv[1])