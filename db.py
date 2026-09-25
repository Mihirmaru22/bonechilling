""" db.py - works as communitcator to SQLite"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "Xray.db"


def connect():
    """ Open the database and make sure the tables exist. """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row 
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS patients (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT,
            patient_id   TEXT,
            age          TEXT,
            sex          TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return conn

def add_patient(conn, name, patient_id=None, age=None, sex=None):
    cur = conn.execute(
        "INSERT INTO patients (name, patient_id, age, sex) VALUES (?, ?, ?, ?)",
        (name, patient_id, age, sex)
    )
    conn.commit()
    return cur.lastrowid

def all_patients(conn):
    return conn.execute("SELECT * FROM patients ORDER BY id").fetchall()

if __name__ == "__main__":
    # SELF-TEST: python db.p
    c = connect()
    new_id = add_patient(c, "TEST patient", "000001", "35", "M")
    print("inserted id:", new_id)
    for row in all_patients(c):
        print(dict(row))

    c.execute("DELETE FROM patients WHERE id = ?", (new_id,)) 
    c.commit()
    print("self-test done, test row removed ")
    