"""db.py — the only module that talks to SQLite.

Rebuilt from the original root db.py with the industrial-grade fixes:
- Patient identity is the FOLDER, not the OCR'd name (the old code merged two
  different people who shared a name, and split one patient on an OCR typo).
- Idempotency: images carry a UNIQUE file_sha256, so re-dropping a folder does
  not create duplicates.
- Audit: every image row records which engine/model produced it, its
  confidence, latency, any error, the raw response, and the OCR-vs-VLM
  cross-check — so a doctor (or an auditor) can see provenance.
- Versioned migrations via PRAGMA user_version instead of ad-hoc ALTER blocks.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1


def default_db_path() -> Path:
    """Per-user DB outside the repo. Override with $BONECHILLING_DB."""
    env = os.environ.get("BONECHILLING_DB")
    if env:
        return Path(env)
    root = Path.home() / ".bonechilling"
    root.mkdir(parents=True, exist_ok=True)
    return root / "bonechilling.db"


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn)
    return conn


# --------------------------------------------------------------------------- #
# Migrations
# --------------------------------------------------------------------------- #
def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                folder_path       TEXT UNIQUE,
                display_name      TEXT,
                name              TEXT,
                age               TEXT,
                sex               TEXT,
                patient_id        TEXT,
                review_status     TEXT DEFAULT 'unreviewed',
                surgeon_notes     TEXT DEFAULT '',
                reviewed_at       TIMESTAMP,
                verified_hardware TEXT,
                verified_facts    TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS images (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id      INTEGER,
                file_path       TEXT,
                file_sha256     TEXT UNIQUE,
                study_date      TEXT,
                body_part       TEXT,
                laterality      TEXT,
                views           TEXT,
                raw_ocr         TEXT,
                label_json      TEXT,
                crosscheck_json TEXT,
                film_found      INTEGER DEFAULT 0,
                engine_used     TEXT,
                model_name      TEXT,
                confidence      REAL,
                processing_ms   INTEGER,
                error           TEXT,
                raw_response    TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(patient_id) REFERENCES patients(id)
            );
            CREATE TABLE IF NOT EXISTS findings (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id         INTEGER,
                hardware         TEXT,
                visible_findings TEXT,
                impression       TEXT,
                image_quality    TEXT,
                confidence       REAL,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(image_id) REFERENCES images(id)
            );
            CREATE INDEX IF NOT EXISTS idx_images_patient ON images(patient_id);
            CREATE INDEX IF NOT EXISTS idx_findings_image ON findings(image_id);
            """
        )
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    # future: if version < 2: ...


# --------------------------------------------------------------------------- #
# Patients (folder-as-identity)
# --------------------------------------------------------------------------- #
def get_or_create_patient_for_folder(
    conn: sqlite3.Connection, folder_path: str, display_name: Optional[str] = None
) -> int:
    folder_path = str(folder_path)
    row = conn.execute("SELECT id FROM patients WHERE folder_path = ?", (folder_path,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO patients (folder_path, display_name) VALUES (?, ?)",
        (folder_path, display_name or Path(folder_path).name),
    )
    conn.commit()
    return cur.lastrowid


def update_patient_demographics(conn: sqlite3.Connection, patient_id: int, **fields: Any) -> None:
    allowed = {"display_name", "name", "age", "sex", "patient_id"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            params.append(str(v))
    if not sets:
        return
    params.append(patient_id)
    conn.execute(f"UPDATE patients SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()


# --------------------------------------------------------------------------- #
# Images (idempotent)
# --------------------------------------------------------------------------- #
def image_exists(conn: sqlite3.Connection, file_sha256: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM images WHERE file_sha256 = ?", (file_sha256,)
    ).fetchone() is not None


def save_analysis(conn: sqlite3.Connection, patient_id: int, record: Dict[str, Any]) -> Optional[int]:
    """Atomically persist one analyzed image + its findings.

    Idempotent: if the sha already exists, returns None and writes nothing.
    `record` keys: file_path, file_sha256, raw_ocr(list), facts(XrayFacts),
    crosscheck(dict), film_found(bool), engine, latency_ms, error, raw_response.
    """
    sha = record["file_sha256"]
    if image_exists(conn, sha):
        return None

    facts = record["facts"]
    views = facts.views or []
    label = facts.label.model_dump() if facts.label else {}
    hardware = [h.model_dump() for h in facts.hardware]

    with conn:  # transaction: commit on success, rollback on error
        cur = conn.execute(
            """INSERT INTO images
               (patient_id, file_path, file_sha256, study_date, body_part, laterality,
                views, raw_ocr, label_json, crosscheck_json, film_found,
                engine_used, model_name, confidence, processing_ms, error, raw_response)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                patient_id,
                record["file_path"],
                sha,
                record.get("study_date"),
                facts.body_part,
                facts.laterality,
                json.dumps(views),
                "\n".join(record.get("raw_ocr", []) or []),
                json.dumps(label),
                json.dumps(record.get("crosscheck", {})),
                1 if record.get("film_found") else 0,
                record.get("engine"),
                record.get("model_name"),
                facts.confidence,
                record.get("latency_ms"),
                record.get("error"),
                (record.get("raw_response") or "")[:8000],
            ),
        )
        image_id = cur.lastrowid
        conn.execute(
            """INSERT INTO findings
               (image_id, hardware, visible_findings, impression, image_quality, confidence)
               VALUES (?,?,?,?,?,?)""",
            (
                image_id,
                json.dumps(hardware),
                json.dumps(facts.visible_findings or []),
                facts.impression,
                facts.image_quality,
                facts.confidence,
            ),
        )
    return image_id


# --------------------------------------------------------------------------- #
# Read helpers (minimal — richer summary/reconcile comes with the UI slice)
# --------------------------------------------------------------------------- #
def list_patients(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT p.*, COUNT(i.id) AS image_count
           FROM patients p LEFT JOIN images i ON i.patient_id = p.id
           GROUP BY p.id ORDER BY p.id"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_patient_images(conn: sqlite3.Connection, patient_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """SELECT i.*, f.hardware, f.visible_findings, f.impression, f.image_quality
           FROM images i LEFT JOIN findings f ON f.image_id = i.id
           WHERE i.patient_id = ? ORDER BY i.id""",
        (patient_id,),
    ).fetchall()
    return [dict(r) for r in rows]
