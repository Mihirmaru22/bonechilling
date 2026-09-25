"""db.py — the only file allowed to talk to SQLite."""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "xray.db"

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Create all three tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT,
            patient_id TEXT,
            age        TEXT,
            sex        TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            file_path  TEXT,
            study_date TEXT,
            body_part  TEXT,
            views      TEXT,  
            raw_ocr    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_id) REFERENCES patients(id)
        );
        CREATE TABLE IF NOT EXISTS findings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id   INTEGER,
            hardware   TEXT,  
            impression TEXT,
            confidence REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(image_id) REFERENCES images(id)
        );
    """)
    return conn

def save_record(conn, record):
    """Saves the patient, image, and findings in one atomic transaction."""
    with conn:  # auto-commits if successful, auto-rolls-back if it crashes
        # 1. Save Patient
        cur = conn.execute(
            "INSERT INTO patients (name, patient_id, age, sex) VALUES (?, ?, ?, ?)",
            (record['norm']['name'], record['norm'].get('accession_or_id'),
             record['norm']['age'], record['norm']['sex'])
        )
        pid = cur.lastrowid

        # 2. Save Image (lists like 'views' are stored as JSON strings)
        cur = conn.execute(
            "INSERT INTO images (patient_id, file_path, study_date, body_part, views, raw_ocr) VALUES (?, ?, ?, ?, ?, ?)",
            (pid, record['file_path'], record['norm']['study_date'],
             record['norm']['body_part'], json.dumps(record['norm']['views']),
             "\n".join(record['raw_ocr']))
        )
        img_id = cur.lastrowid

        # 3. Save Findings
        conn.execute(
            "INSERT INTO findings (image_id, hardware, impression, confidence) VALUES (?, ?, ?, ?)",
            (img_id, json.dumps(record['vision']['hardware']),
             record['vision']['impression'], record['vision']['confidence'])
        )
    return pid