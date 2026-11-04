# Legacy (v1) — archived

These are the original flat scripts and the PySide6 desktop app. They have been
**superseded** by the `bonechiling` package under [`../src/bonechiling/`](../src/bonechiling/)
and are kept only for reference and history.

| legacy file | replaced by |
|---|---|
| `ocr.py` | `bonechiling/core/ocr.py` (pluggable backends, film-aware) |
| `normalize.py` | `bonechiling/core/normalize.py` (multi-format, per-field confidence) |
| `vision.py` | `bonechiling/engines/*` (5 providers) + `core/prefilter.py` |
| `db.py` | `bonechiling/data/db.py` (folder-as-patient, idempotent, audit) + `core/reconcile.py` |
| `pipeline.py` | `bonechiling/pipeline/runner.py` |
| `worker.py` | `bonechiling/pipeline/runner.py` + `api/jobs.py` (WebSocket progress) |
| `import_page.py`, `main.py` | `bonechiling/webui/` + `api/server.py` + `desktop/app.py` |
| `evaluate_test_batch.py` | `bonechiling/eval/harness.py` (accuracy vs ground truth) |

These modules import each other by bare filename, so if you must run one, do it
from inside this `legacy/` directory. New work should target the package, not
these files.
