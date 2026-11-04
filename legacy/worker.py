"""worker.py — High-performance background ingestion queue for multi-patient X-ray batches."""
import os
import sys
import time
import threading
from collections import deque
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QCoreApplication

from ocr import ocr_lines
from normalize import normalize
from vision import analyze, is_likely_xray
from db import (
    connect, save_record, get_or_create_patient,
    reconcile_patient_study_hardware
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".dcm", ".dicom"}


def discover_patient_folders(paths):
    """
    Given a list or single path of files/directories (e.g. from Drag & Drop or FileDialog),
    returns a deduplicated list of Path objects representing patient folders.
    
    Robustly handles:
    - 50 patient folders selected and dropped together.
    - A single batch root directory containing 50 patient subfolders.
    - Deeply nested directory trees (e.g. Hospital/Ward/Patient/Images/*.jpg).
    - Loose image files (groups them by their parent directory).
    """
    if isinstance(paths, (str, Path)):
        paths = [paths]

    patient_dirs = []
    seen = set()

    def add_if_valid(p):
        p_res = Path(p).resolve()
        if p_res not in seen and p_res.is_dir() and not p_res.name.startswith("."):
            has_img = any(
                f.suffix.lower() in IMAGE_EXTS
                for f in p_res.iterdir()
                if f.is_file() and not f.name.startswith(".")
            )
            if has_img:
                seen.add(p_res)
                patient_dirs.append(p_res)
                return True
        return False

    for item in paths:
        p = Path(item).resolve()
        if not p.exists():
            continue

        if p.is_file():
            if p.suffix.lower() in IMAGE_EXTS:
                add_if_valid(p.parent)
        elif p.is_dir():
            # Check if this directory directly has images
            p_has_images = any(
                f.suffix.lower() in IMAGE_EXTS
                for f in p.iterdir()
                if f.is_file() and not f.name.startswith(".")
            )

            # Check if directory has subdirectories (e.g. batch root of 50 folders)
            subdirs = [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")]

            if subdirs:
                # Walk tree to find every directory containing images
                found_in_subs = False
                for root, dirs, files in os.walk(str(p)):
                    # Ignore hidden and macOS metadata folders
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__MACOSX"]
                    if any(Path(f).suffix.lower() in IMAGE_EXTS for f in files if not f.startswith(".")):
                        candidate = Path(root).resolve()
                        if candidate not in seen:
                            seen.add(candidate)
                            patient_dirs.append(candidate)
                            found_in_subs = True

                if not found_in_subs and p_has_images:
                    add_if_valid(p)
            elif p_has_images:
                add_if_valid(p)

    return sorted(patient_dirs, key=lambda x: str(x).lower())


get_patient_folders = discover_patient_folders  # backward compatibility


class IngestionQueueWorker(QThread):
    """
    Continuous background queue worker:
    Enables dropping or adding large batches (e.g. 50 patient folders) into a FIFO queue.
    Runs asynchronously in the background so the physician can continue reviewing
    already-processed cases in the UI with zero interruption or thread freezing.
    """
    queue_updated       = Signal(int, int, str)    # (completed_folders, total_folders, message)
    progress            = Signal(int, str)         # (overall_percentage, message)
    item_done           = Signal(dict)             # one finished film record
    patient_ingested    = Signal(int, str, int)    # (patient_id, patient_name, count)
    finished_ok         = Signal(int)              # total processed X-rays (backward compat)
    all_completed       = Signal(int, int)         # (total_folders, total_xrays)
    failed              = Signal(str)              # error message
    queue_state_changed = Signal(dict)             # rich queue status for Queue Manager modal

    def __init__(self, initial_folder=None, parent=None):
        super().__init__(parent)
        self._lock = threading.Lock()
        self._queue = deque()
        self._completed_folders = 0
        self._total_enqueued = 0
        self._total_processed_xrays = 0
        self._current_folder = None
        self._current_film = None
        self._is_paused = False
        self._is_stopped = False
        self._session_start = None
        self._history = []

        if initial_folder:
            self.enqueue_folders(initial_folder)

    def enqueue_folders(self, paths):
        """
        Thread-safe enqueueing of one or multiple folders (e.g. 50 folders).
        Can be called at ANY time, even while ingestion is currently running.
        """
        discovered = discover_patient_folders(paths)
        if not discovered:
            return 0

        with self._lock:
            added = 0
            if self._session_start is None:
                self._session_start = time.time()

            for d in discovered:
                if d not in self._queue and d != self._current_folder:
                    self._queue.append(d)
                    self._total_enqueued += 1
                    added += 1

            total = self._total_enqueued
            comp = self._completed_folders

        if added > 0:
            msg = f"Enqueued {added} folders ({len(self._queue)} pending, {comp}/{total} completed)"
            self.queue_updated.emit(comp, total, msg)
            self.queue_state_changed.emit(self.get_status())

            # Start worker thread if not already running
            if not self.isRunning():
                self._is_stopped = False
                self.start()

        return added

    def pause(self):
        with self._lock:
            self._is_paused = True
        self.queue_state_changed.emit(self.get_status())

    def resume(self):
        with self._lock:
            self._is_paused = False
        self.queue_state_changed.emit(self.get_status())

    def toggle_pause(self):
        with self._lock:
            self._is_paused = not self._is_paused
            state = self._is_paused
        self.queue_state_changed.emit(self.get_status())
        return state

    def clear_queue(self):
        """Clears pending folders from queue without halting active folder analysis."""
        with self._lock:
            cleared_count = len(self._queue)
            self._queue.clear()
            self._total_enqueued = self._completed_folders + (1 if self._current_folder else 0)
            comp = self._completed_folders
            total = self._total_enqueued

        self.queue_updated.emit(comp, total, f"Queue cleared ({cleared_count} pending folders removed)")
        self.queue_state_changed.emit(self.get_status())
        return cleared_count

    def stop(self):
        self._is_stopped = True
        self.resume()

    def get_status(self):
        with self._lock:
            now = time.time()
            elapsed = (now - self._session_start) if self._session_start else 0.0
            avg_sec = (elapsed / max(1, self._total_processed_xrays)) if self._total_processed_xrays > 0 else 0.0
            pending_names = [p.name for p in list(self._queue)]

            return {
                "pending": len(self._queue),
                "completed": self._completed_folders,
                "total": self._total_enqueued,
                "pending_count": len(self._queue),
                "completed_count": self._completed_folders,
                "total_count": self._total_enqueued,
                "total_xrays": self._total_processed_xrays,
                "is_running": self.isRunning(),
                "is_paused": self._is_paused,
                "current_folder": self._current_folder.name if self._current_folder else None,
                "current_film": self._current_film,
                "pending_folders": pending_names,
                "history": list(self._history[-30:]),
                "avg_film_sec": round(avg_sec, 2),
                "elapsed_sec": round(elapsed, 1)
            }

    def run(self):
        """Main queue execution loop in background thread with zero-interruption execution."""
        conn = connect()

        if self._session_start is None:
            self._session_start = time.time()

        while not self._is_stopped:
            while self._is_paused and not self._is_stopped:
                self.msleep(100)

            with self._lock:
                if not self._queue:
                    break
                p_folder = self._queue.popleft()
                self._current_folder = p_folder
                self._current_film = None
                current_idx = self._completed_folders + 1
                total_folders = self._total_enqueued
                completed_folders = self._completed_folders

            pct = int((completed_folders / max(1, total_folders)) * 100)
            self.progress.emit(pct, f"Analyzing [{current_idx}/{total_folders}]: {p_folder.name}")
            self.queue_updated.emit(
                completed_folders, total_folders,
                f"Ingesting [{current_idx}/{total_folders}]: {p_folder.name}"
            )
            self.queue_state_changed.emit(self.get_status())

            # Find all images in folder
            imgs = [
                f for f in p_folder.iterdir()
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in IMAGE_EXTS
            ]

            if not imgs:
                with self._lock:
                    self._completed_folders += 1
                    self._history.append({
                        "name": p_folder.name,
                        "status": "skipped",
                        "films": 0,
                        "message": "No supported image files found"
                    })
                    self._current_folder = None
                continue

            folder_patient_id = None
            patient_name = p_folder.name
            folder_xrays = 0
            folder_start = time.time()

            for f_idx, img_path in enumerate(imgs):
                if self._is_stopped:
                    break
                while self._is_paused and not self._is_stopped:
                    self.msleep(100)

                with self._lock:
                    self._current_film = img_path.name
                self.queue_state_changed.emit(self.get_status())

                # 1. Fast pre-filter: silently skip non-X-rays
                try:
                    if not is_likely_xray(img_path):
                        continue
                except Exception:
                    pass

                # 2. OCR text extraction & field normalization with exception guard
                try:
                    lines = ocr_lines(img_path)
                    norm = normalize(lines)
                except Exception as ocr_err:
                    lines = []
                    norm = {
                        "name": p_folder.name,
                        "accession_or_id": None,
                        "age": None,
                        "sex": None,
                        "body_part": None,
                        "views": []
                    }

                # 3. Vision AI radiographic facts analysis with resilient fallback
                try:
                    vision = analyze(img_path)
                except Exception as vis_err:
                    # Graceful fallback: construct fallback facts if vision AI is unreachable
                    part_guess = norm.get("body_part") or "General Skeletal"
                    vision = {
                        "is_xray": True,
                        "image_type": "X-ray",
                        "body_part": part_guess,
                        "views": norm.get("views") or [],
                        "hardware": [],
                        "visible_findings": [f"Radiograph loaded: {img_path.name}."],
                        "impression": f"Radiographic study for {norm.get('name') or p_folder.name} ({part_guess}). [Note: Ollama was unreachable at http://localhost:11434. Please start Ollama with 'ollama run qwen2.5vl:3b' for full AI analysis.]"
                    }

                if not vision.get("is_xray", False):
                    continue

                # 4. Resolve Patient ID for this patient's folder
                if folder_patient_id is None:
                    patient_name = norm.get('name') or p_folder.name
                    folder_patient_id = get_or_create_patient(
                        conn,
                        name=patient_name,
                        patient_id=norm.get('accession_or_id'),
                        age=norm.get('age'),
                        sex=norm.get('sex')
                    )

                # 5. Save image & findings under the folder's patient (atomic commit)
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
                folder_xrays += 1
                self._total_processed_xrays += 1
                self.item_done.emit(record)

            # 6. Reconcile multi-angle hardware across all views for this patient
            if folder_patient_id:
                reconcile_patient_study_hardware(conn, folder_patient_id)
                self.patient_ingested.emit(folder_patient_id, patient_name, folder_xrays)

            dur = round(time.time() - folder_start, 1)
            with self._lock:
                self._completed_folders += 1
                self._history.append({
                    "name": patient_name,
                    "folder": p_folder.name,
                    "status": "completed",
                    "films": folder_xrays,
                    "duration_sec": dur
                })
                self._current_folder = None
                self._current_film = None
                completed_folders = self._completed_folders
                total_folders = self._total_enqueued

            pct_done = int((completed_folders / max(1, total_folders)) * 100)
            self.progress.emit(pct_done, f"Completed: {patient_name} ({completed_folders}/{total_folders})")
            self.queue_updated.emit(
                completed_folders, total_folders,
                f"Finished {patient_name} ({completed_folders}/{total_folders} studies ready)"
            )
            self.queue_state_changed.emit(self.get_status())

        conn.close()

        if not self._is_stopped:
            self.progress.emit(100, f"All studies ingested ({self._completed_folders} folders, {self._total_processed_xrays} X-rays)")
            self.finished_ok.emit(self._total_processed_xrays)
            self.all_completed.emit(self._completed_folders, self._total_processed_xrays)
            self.queue_state_changed.emit(self.get_status())


# Backward compatible alias
PipelineWorker = IngestionQueueWorker


if __name__ == "__main__":
    # SELF-TEST: python worker.py test
    app = QCoreApplication(sys.argv)

    def on_progress(percent, msg):
        print(f"[{percent:3d}%] {msg}")

    def on_item_done(record):
        print(f"   -> Saved: {record['norm']['name']} (ID: {record['patient_id']})")

    def on_finished(count):
        print(f"\nFinished processing {count} images.")
        app.quit()

    def on_failed(err):
        print(f"ERROR: {err}")
        app.quit()

    if len(sys.argv) != 2:
        print("usage: python worker.py <folder>")
        sys.exit(1)

    worker = PipelineWorker(sys.argv[1])
    worker.progress.connect(on_progress)
    worker.item_done.connect(on_item_done)
    worker.finished_ok.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.start()

    sys.exit(app.exec())