"""worker.py — runs the pipeline in the background so the UI never freezes."""
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QCoreApplication

from ocr import ocr_lines
from normalize import normalize
from vision import analyze
from db import connect, save_record

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


class PipelineWorker(QThread):
    # Signals are our radio channels to talk to the main UI thread safely
    progress   = Signal(int, str)   # (percent, message)
    item_done  = Signal(dict)       # one finished record
    finished_ok = Signal(int)       # total images processed
    failed     = Signal(str)        # error message

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = Path(folder_path)

    def run(self):
        """This method executes in the background thread."""
        try:
            if not self.folder_path.is_dir():
                self.failed.emit(f"Not a folder: {self.folder_path}")
                return

            conn = connect()
            images = [f for f in self.folder_path.iterdir() if f.suffix.lower() in IMAGE_EXTS]
            total = len(images)
            
            if total == 0:
                self.progress.emit(100, "No images found.")
                self.finished_ok.emit(0)
                return

            for i, img_path in enumerate(images, 1):
                # Tell UI we are starting a new file
                self.progress.emit(int((i - 1) / total * 100), f"Processing {img_path.name}...")

                # 1. OCR & Normalize
                lines = ocr_lines(img_path)
                norm = normalize(lines)

                # 2. Vision AI
                vision = analyze(img_path)

                # 3. Database
                record = {
                    "file_path": str(img_path.resolve()),
                    "file_name": img_path.name,
                    "raw_ocr": lines,
                    "norm": norm,
                    "vision": vision,
                }
                pid = save_record(conn, record)
                record["patient_id"] = pid
                
                # Tell UI we finished this specific file
                self.item_done.emit(record)

            # Tell UI we are completely done
            self.progress.emit(100, "All done!")
            self.finished_ok.emit(total)

        except Exception as e:
            self.failed.emit(str(e))


if __name__ == "__main__":
    # SELF-TEST: python worker.py data
    # We use QCoreApplication (headless Qt) just to test the signals without a window.
    app = QCoreApplication(sys.argv)

    def on_progress(percent, msg):
        print(f"[{percent:3d}%] {msg}")
    
    def on_item_done(record):
        print(f"   -> Saved: {record['norm']['name']} (ID: {record['patient_id']})")

    def on_finished(count):
        print(f"\nFinished processing {count} images.")
        app.quit()  # stops the test

    def on_failed(err):
        print(f"ERROR: {err}")
        app.quit()

    if len(sys.argv) != 2:
        print("usage: python worker.py <folder>")
        sys.exit(1)

    worker = PipelineWorker(sys.argv[1])
    
    # Connect the radio channels
    worker.progress.connect(on_progress)
    worker.item_done.connect(on_item_done)
    worker.finished_ok.connect(on_finished)
    worker.failed.connect(on_failed)
    
    # CRITICAL: start() spawns the thread. run() would freeze the main thread!
    worker.start() 
    
    sys.exit(app.exec())