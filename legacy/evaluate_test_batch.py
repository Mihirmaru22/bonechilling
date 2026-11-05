"""evaluate_test_batch.py — runs the entire pipeline on the test dataset with timing & metrics."""
import json
import time
from pathlib import Path

from ocr import ocr_lines
from normalize import normalize
from vision import analyze, is_likely_xray
from db import connect, save_record, get_or_create_patient, get_all_records

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

def run_evaluation(test_dir="test"):
    root = Path(test_dir)
    folders = sorted([d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")])
    print(f"==================================================")
    print(f"STARTING BATCH EVALUATION ON {len(folders)} FOLDERS")
    print(f"==================================================")

    conn = connect()
    overall_start = time.time()

    all_results = []
    folder_summaries = []

    for folder in folders:
        f_start = time.time()
        imgs = sorted([f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS])
        print(f"\n📁 FOLDER [{folder.name}] — {len(imgs)} files")
        print("-" * 50)

        folder_patient_id = None
        folder_patient_name = None
        folder_xray_count = 0
        folder_skipped_count = 0

        for idx, img_path in enumerate(imgs, 1):
            img_start = time.time()
            print(f"[{idx}/{len(imgs)}] File: {img_path.name}")

            # 1. Fast pre-filter
            t0 = time.time()
            likely_xray = is_likely_xray(img_path)
            t_filter = time.time() - t0

            if not likely_xray:
                t_total = time.time() - img_start
                folder_skipped_count += 1
                res = {
                    "folder": folder.name,
                    "filename": img_path.name,
                    "is_xray": False,
                    "skip_reason": "Failed fast heuristic (document or color photo)",
                    "timings": {
                        "filter_sec": round(t_filter, 4),
                        "total_sec": round(t_total, 3)
                    }
                }
                all_results.append(res)
                print(f"   ⏩ SKIPPED (Non-X-ray detected in {t_filter*1000:.1f}ms)")
                continue

            # 2. OCR
            t0 = time.time()
            lines = ocr_lines(img_path)
            t_ocr = time.time() - t0

            # 3. Normalization
            t0 = time.time()
            norm = normalize(lines)
            t_norm = time.time() - t0

            # 4. Vision AI analysis
            t0 = time.time()
            vision = analyze(img_path)
            t_vision = time.time() - t0

            if not vision.get("is_xray", False):
                t_total = time.time() - img_start
                folder_skipped_count += 1
                res = {
                    "folder": folder.name,
                    "filename": img_path.name,
                    "is_xray": False,
                    "skip_reason": "Vision model identified non-X-ray",
                    "timings": {
                        "filter_sec": round(t_filter, 4),
                        "ocr_sec": round(t_ocr, 3),
                        "norm_sec": round(t_norm, 4),
                        "vision_sec": round(t_vision, 2),
                        "total_sec": round(t_total, 3)
                    }
                }
                all_results.append(res)
                print(f"   ⏩ SKIPPED (Model identified non-X-ray in {t_vision:.2f}s)")
                continue

            # 5. Patient ID linking (shared per folder)
            t0 = time.time()
            if folder_patient_id is None:
                folder_patient_name = norm.get('name') or f"Patient_{folder.name}"
                folder_patient_id = get_or_create_patient(
                    conn,
                    name=folder_patient_name,
                    patient_id=norm.get('accession_or_id'),
                    age=norm.get('age'),
                    sex=norm.get('sex')
                )

            record = {
                "file_path": str(img_path.resolve()),
                "file_name": img_path.name,
                "folder_name": folder.name,
                "raw_ocr": lines,
                "norm": norm,
                "vision": vision,
                "patient_id": folder_patient_id,
            }
            save_record(conn, record, patient_id=folder_patient_id)
            t_db = time.time() - t0
            t_total = time.time() - img_start

            folder_xray_count += 1

            res = {
                "folder": folder.name,
                "filename": img_path.name,
                "is_xray": True,
                "patient_id": folder_patient_id,
                "patient_name": folder_patient_name,
                "age_sex": f"{norm.get('age') or '?'}/{norm.get('sex') or '?'}",
                "accession": norm.get('accession_or_id'),
                "ocr_lines_count": len(lines),
                "body_part": norm.get('body_part') or vision.get('body_part'),
                "views": norm.get('views') or vision.get('views', []),
                "hardware": vision.get('hardware', []),
                "impression": vision.get('impression'),
                "confidence": vision.get('confidence'),
                "timings": {
                    "filter_sec": round(t_filter, 4),
                    "ocr_sec": round(t_ocr, 3),
                    "norm_sec": round(t_norm, 4),
                    "vision_sec": round(t_vision, 2),
                    "db_sec": round(t_db, 4),
                    "total_sec": round(t_total, 2)
                }
            }
            all_results.append(res)

            print(f"   ✅ Patient: {folder_patient_name} | Part: {res['body_part']} | Views: {res['views']}")
            print(f"   ⏱  Timing: OCR={t_ocr:.2f}s, Vision={t_vision:.2f}s, Total={t_total:.2f}s")
            print(f"   🔍 Hardware: {res['hardware']}")
            print(f"   💡 Impression: {res['impression'][:120]}...")

        f_total = time.time() - f_start
        f_summary = {
            "folder": folder.name,
            "total_files": len(imgs),
            "xrays_processed": folder_xray_count,
            "non_xrays_skipped": folder_skipped_count,
            "patient_name": folder_patient_name,
            "total_time_sec": round(f_total, 2),
            "avg_time_per_xray": round(f_total / folder_xray_count, 2) if folder_xray_count > 0 else 0
        }
        folder_summaries.append(f_summary)
        print(f"\n🏁 Finished Folder {folder.name}: {folder_xray_count} X-rays in {f_total:.2f}s")

    overall_total = time.time() - overall_start

    # Save detailed JSON report
    report = {
        "overall_time_sec": round(overall_total, 2),
        "total_folders": len(folders),
        "folder_summaries": folder_summaries,
        "detailed_results": all_results
    }
    with open("eval_results.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 50)
    print(f"BATCH EVALUATION COMPLETED IN {overall_total:.2f}s ({overall_total/60:.2f} min)")
    print("=" * 50)
    return report

if __name__ == "__main__":
    run_evaluation()
