"""db.py — the only file allowed to talk to SQLite."""
import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "xray.db"

def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Create all three tables
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT,
            patient_id         TEXT,
            age                TEXT,
            sex                TEXT,
            review_status      TEXT DEFAULT 'unreviewed',
            surgeon_notes      TEXT DEFAULT '',
            reviewed_at        TIMESTAMP,
            verified_hardware  TEXT,
            verified_facts     TEXT,
            created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

    # Auto-migration for existing tables
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(patients)")
    cols = {row["name"] for row in cursor.fetchall()}
    if "review_status" not in cols:
        conn.execute("ALTER TABLE patients ADD COLUMN review_status TEXT DEFAULT 'unreviewed'")
    if "surgeon_notes" not in cols:
        conn.execute("ALTER TABLE patients ADD COLUMN surgeon_notes TEXT DEFAULT ''")
    if "reviewed_at" not in cols:
        conn.execute("ALTER TABLE patients ADD COLUMN reviewed_at TIMESTAMP")
    if "verified_hardware" not in cols:
        conn.execute("ALTER TABLE patients ADD COLUMN verified_hardware TEXT")
    if "verified_facts" not in cols:
        conn.execute("ALTER TABLE patients ADD COLUMN verified_facts TEXT")
    conn.commit()

    return conn

def get_or_create_patient(conn, name, patient_id=None, age=None, sex=None):
    """Finds an existing patient or creates one, avoiding duplicate patient entries."""
    if patient_id:
        row = conn.execute("SELECT id FROM patients WHERE patient_id = ?", (str(patient_id),)).fetchone()
        if row:
            return row["id"]

    if name:
        row = conn.execute("SELECT id FROM patients WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]

    cur = conn.execute(
        "INSERT INTO patients (name, patient_id, age, sex) VALUES (?, ?, ?, ?)",
        (name or "Unknown Patient", str(patient_id) if patient_id else None, str(age) if age else None, sex)
    )
    return cur.lastrowid

def save_record(conn, record, patient_id=None):
    """Saves the patient (if not already known), image, and findings in one atomic transaction."""
    with conn:  # auto-commits if successful, auto-rolls-back if it crashes
        if patient_id is None:
            patient_id = get_or_create_patient(
                conn,
                name=record['norm'].get('name'),
                patient_id=record['norm'].get('accession_or_id'),
                age=record['norm'].get('age'),
                sex=record['norm'].get('sex')
            )

        # 2. Save Image (lists like 'views' are stored as JSON strings)
        views = record['norm'].get('views') or record['vision'].get('views', [])
        body_part = record['norm'].get('body_part') or record['vision'].get('body_part')
        cur = conn.execute(
            "INSERT INTO images (patient_id, file_path, study_date, body_part, views, raw_ocr) VALUES (?, ?, ?, ?, ?, ?)",
            (patient_id, record['file_path'], record['norm'].get('study_date'),
             body_part, json.dumps(views),
             "\n".join(record.get('raw_ocr', [])))
        )
        img_id = cur.lastrowid

        # 3. Save Findings
        conn.execute(
            "INSERT INTO findings (image_id, hardware, impression, confidence) VALUES (?, ?, ?, ?)",
            (img_id, json.dumps(record['vision'].get('hardware', [])),
             record['vision'].get('impression'), record['vision'].get('confidence', 0.0))
        )
    return patient_id

def update_patient_review(conn, patient_id, review_status=None, surgeon_notes=None, verified_hardware=None, verified_facts=None):
    """Updates surgeon verification status, clinical notes, and edited findings for a patient."""
    updates = []
    params = []
    if review_status is not None:
        updates.append("review_status = ?")
        params.append(review_status)
    if surgeon_notes is not None:
        updates.append("surgeon_notes = ?")
        params.append(surgeon_notes)
    if verified_hardware is not None:
        updates.append("verified_hardware = ?")
        params.append(verified_hardware)
    if verified_facts is not None:
        updates.append("verified_facts = ?")
        params.append(verified_facts)

    updates.append("reviewed_at = CURRENT_TIMESTAMP")
    params.append(patient_id)

    sql = f"UPDATE patients SET {', '.join(updates)} WHERE id = ?"
    conn.execute(sql, params)
    conn.commit()

def get_all_records(conn):
    """Retrieve raw joined records."""
    query = """
        SELECT 
            p.id AS patient_id,
            p.name,
            p.age,
            p.sex,
            p.patient_id AS hospital_id,
            p.review_status,
            p.surgeon_notes,
            p.reviewed_at,
            p.verified_hardware,
            p.verified_facts,
            i.id AS image_id,
            i.file_path,
            i.study_date,
            i.body_part,
            i.views,
            f.hardware,
            f.impression
        FROM patients p
        JOIN images i ON p.id = i.patient_id
        LEFT JOIN findings f ON i.id = f.image_id
        ORDER BY p.id ASC, i.id ASC
    """
    return conn.execute(query).fetchall()

def normalize_text(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())

def parse_views(views_raw):
    """Normalize views into a set of standard projection codes: {'AP', 'LAT', etc.}"""
    if not views_raw:
        return set()
    s = str(views_raw)
    if s.startswith("["):
        try:
            arr = json.loads(s)
            s = " ".join(str(x) for x in arr)
        except Exception:
            pass
    v_upper = s.upper()
    found = set()
    if "AP" in v_upper or "ANTEROPOSTERIOR" in v_upper or "ANTERIOR" in v_upper:
        found.add("AP")
    if "PA" in v_upper or "POSTEROANTERIOR" in v_upper or "POSTERIOR" in v_upper:
        found.add("PA")
    if "LAT" in v_upper or "LATERAL" in v_upper:
        found.add("LAT")
    if "MORTISE" in v_upper:
        found.add("MORTISE")
    if "OBLIQUE" in v_upper:
        found.add("OBLIQUE")
    if "AXIAL" in v_upper:
        found.add("AXIAL")
    return found

def are_orthogonal(views_set):
    """Returns True if the set contains orthogonal projections (e.g. AP/PA and LAT)."""
    has_coronal = bool(views_set & {"AP", "PA"})
    has_sagittal = bool(views_set & {"LAT"})
    return has_coronal and has_sagittal

def categorize_implant(text):
    t = normalize_text(text)
    if "k-wire" in t or "kwire" in t or "kirschner" in t:
        return "k_wire", "K-wires"
    if "plate" in t or "dcp" in t or "lcp" in t:
        return "plate", "plate"
    if "nail" in t or "rod" in t or "intramedullary" in t:
        return "nail", "nail"
    if "screw" in t or "screws" in t:
        return "screw", "screws"
    if "total hip" in t or "replacement" in t or "stem" in t or "prosthesis" in t or "arthroplasty" in t:
        return "arthroplasty", "arthroplasty"
    if "wire" in t or "cerclage" in t or "tension band" in t:
        return "wire", "wire"
    return "other", text.strip()

def extract_location(text):
    t = normalize_text(text)
    loc_keywords = [
        "medial condyle", "lateral condyle", "femoral neck", "femoral head",
        "distal femur", "proximal femur", "femur",
        "olecranon", "radial head", "distal radius", "radius", "ulna",
        "medial malleolus", "lateral malleolus", "distal tibia", "proximal tibia", "tibia", "fibula",
        "acetabulum", "pelvis", "greater trochanter", "lesser trochanter",
        "humeral head", "shaft", "glenoid", "clavicle", "patella"
    ]
    for loc in loc_keywords:
        if loc in t:
            return loc
    return ""

def parse_single_hardware_item(item):
    """Parse string or dict into structured hardware record."""
    if isinstance(item, dict):
        imp = item.get("implant", "")
        loc = item.get("location", "")
        count = item.get("count", 1)
        integrity = item.get("integrity", "intact")
        cat, std_name = categorize_implant(imp)
        if not loc:
            loc = extract_location(imp)
        return {
            "implant_category": cat,
            "display_name": imp or std_name,
            "location": normalize_text(loc),
            "count": int(count) if count else 1,
            "secondary_count": None,
            "secondary_name": None,
            "integrity": normalize_text(integrity) or "intact",
            "raw": f"{imp} at {loc}".strip()
        }

    s = str(item).strip()
    if not s or s.lower() in ("none", "[]", "null"):
        return None

    # Check integrity in parentheses e.g. (intact)
    integrity = "intact"
    m_int = re.search(r"\(([^)]+)\)", s)
    if m_int:
        int_text = m_int.group(1).lower()
        if "intact" in int_text:
            integrity = "intact"
        elif "loose" in int_text or "displace" in int_text or "break" in int_text:
            integrity = int_text
        s_clean = s[:m_int.start()] + s[m_int.end():]
    else:
        s_clean = s

    # Check for plate with screws e.g. "Olecranon plate with 4 cortical screws"
    secondary_count = None
    secondary_name = None
    m_sec = re.search(r"with\s+(\d+)?\s*([a-zA-Z\s\-]+screws?)", s_clean, re.IGNORECASE)
    if m_sec:
        secondary_count = int(m_sec.group(1)) if m_sec.group(1) else 1
        secondary_name = m_sec.group(2).strip()

    # Extract leading count
    m_cnt = re.search(r"^\s*(\d+)\s*[\.\-]?\s*", s_clean)
    if m_cnt:
        count = int(m_cnt.group(1))
        remainder = s_clean[m_cnt.end():].strip()
    else:
        count = 1
        remainder = s_clean.strip()

    cat, std_name = categorize_implant(remainder)
    loc = extract_location(remainder)

    clean_title = re.sub(r"^(at|in|on|with)\s+", "", remainder, flags=re.IGNORECASE)
    clean_title = clean_title.split(" at ")[0].split(" in ")[0].strip()

    return {
        "implant_category": cat,
        "display_name": clean_title or std_name,
        "location": loc,
        "count": count,
        "secondary_count": secondary_count,
        "secondary_name": secondary_name,
        "integrity": integrity,
        "raw": s
    }

def reconcile_hardware_cross_projections(films):
    """
    Reconciles hardware items across all films and projections for a study.
    Explicitly recognizes when implants visible in orthogonal projections (e.g. AP and Lateral)
    represent the SAME physical hardware construct rather than distinct pieces,
    avoiding double-counting and confirming cross-projection integrity.
    """
    groups = []

    for f in films:
        views = parse_views(f.get('views', ''))
        body_part = normalize_text(f.get('body_part', ''))
        raw_hw = f.get('hardware', '')
        if not raw_hw:
            continue
        try:
            items = json.loads(raw_hw) if isinstance(raw_hw, str) and raw_hw.startswith("[") else [raw_hw]
        except Exception:
            items = [raw_hw]

        for it in items:
            parsed = parse_single_hardware_item(it)
            if not parsed:
                continue

            # Match against existing hardware entity
            matched = None
            for g in groups:
                if g["implant_category"] != parsed["implant_category"]:
                    continue
                loc_match = (
                    g["location"] == parsed["location"] or
                    not g["location"] or not parsed["location"] or
                    g["location"] in parsed["location"] or
                    parsed["location"] in g["location"]
                )
                if not loc_match:
                    continue
                bp_match = (
                    g["body_part"] == body_part or
                    not g["body_part"] or not body_part or
                    g["body_part"] in body_part or
                    body_part in g["body_part"]
                )
                if not bp_match:
                    continue

                matched = g
                break

            if matched:
                matched["views"].update(views)
                matched["counts"].append(parsed["count"])
                if parsed["secondary_count"]:
                    matched["secondary_counts"].append(parsed["secondary_count"])
                if not matched["location"] and parsed["location"]:
                    matched["location"] = parsed["location"]
                if len(parsed["display_name"]) > len(matched["display_name"]):
                    matched["display_name"] = parsed["display_name"]
            else:
                groups.append({
                    "implant_category": parsed["implant_category"],
                    "display_name": parsed["display_name"],
                    "location": parsed["location"],
                    "body_part": body_part,
                    "views": set(views),
                    "counts": [parsed["count"]],
                    "secondary_counts": [parsed["secondary_count"]] if parsed["secondary_count"] else [],
                    "secondary_name": parsed["secondary_name"],
                    "integrity": parsed["integrity"],
                    "raw_samples": [parsed["raw"]]
                })

    if not groups:
        return ["No orthopaedic implants or surgical hardware identified."]

    reconciled_strings = []
    for g in groups:
        final_count = max(g["counts"]) if g["counts"] else 1
        is_ortho = are_orthogonal(g["views"])
        v_list = sorted(g["views"])
        v_str = "/".join(v_list) if v_list else "unspecified"

        if is_ortho:
            view_note = "confirmed on orthogonal AP/LAT views"
        elif len(g["views"]) > 1:
            view_note = f"confirmed across {v_str} views"
        elif g["views"]:
            view_note = f"{v_str} view"
        else:
            view_note = ""

        name = g["display_name"]
        loc = f"at {g['location']}" if g['location'] and g['location'] not in name.lower() else ""

        sec_str = ""
        if g["secondary_counts"] and g["secondary_name"]:
            sec_cnt = max(g["secondary_counts"])
            sec_str = f"with {sec_cnt} {g['secondary_name']}"

        if not re.match(r"^\d+", name):
            if final_count > 1 and not name.lower().endswith("s"):
                count_str = f"{final_count} {name}s"
            else:
                count_str = f"{final_count} {name}"
        else:
            count_str = re.sub(r"^\d+", str(final_count), name)

        parts = [count_str]
        if sec_str and sec_str not in count_str:
            parts.append(sec_str)
        if loc:
            parts.append(loc)

        main_desc = " ".join(parts).strip()
        status_parts = []
        if g["integrity"] and g["integrity"] != "intact":
            status_parts.append(g["integrity"])
        else:
            status_parts.append("intact")
        if view_note:
            status_parts.append(view_note)

        status_str = f"({', '.join(status_parts)})"
        reconciled_strings.append(f"{main_desc} {status_str}")

    return reconciled_strings

def reconcile_patient_study_hardware(conn, patient_id):
    """Helper to query all films for a patient and return reconciled hardware."""
    films = conn.execute("""
        SELECT i.id as image_id, i.body_part, i.views, f.hardware, f.impression
        FROM images i
        LEFT JOIN findings f ON i.id = f.image_id
        WHERE i.patient_id = ?
        ORDER BY i.id
    """, (patient_id,)).fetchall()
    return reconcile_hardware_cross_projections([dict(f) for f in films])

def get_patients_summary(conn):
    """
    Returns 1 consolidated row per patient with all angles, films,
    hardware items, and facts aggregated across multiple projections.
    Includes cross-projection hardware deduplication, surgeon verification status,
    clinical remarks, and overrides.
    """
    rows = get_all_records(conn)
    patients = {}

    for r in rows:
        pid = r['patient_id']
        if pid not in patients:
            patients[pid] = {
                'patient_id': pid,
                'name': r['name'] or 'Unknown Patient',
                'age': r['age'] or '?',
                'sex': r['sex'] or '?',
                'hospital_id': r['hospital_id'] or '—',
                'review_status': r['review_status'] or 'unreviewed',
                'surgeon_notes': r['surgeon_notes'] or '',
                'reviewed_at': r['reviewed_at'],
                'verified_hardware': r['verified_hardware'],
                'verified_facts': r['verified_facts'],
                'film_count': 0,
                'films': [],
                'body_parts': set(),
                'views': set(),
                'impressions': []
            }
        p = patients[pid]
        p['film_count'] += 1
        p['films'].append({
            'image_id': r['image_id'],
            'file_path': r['file_path'],
            'study_date': r['study_date'],
            'body_part': r['body_part'],
            'views': r['views'],
            'hardware': r['hardware'],
            'impression': r['impression']
        })
        if r['body_part']:
            p['body_parts'].add(r['body_part'].title())
        if r['views']:
            try:
                v_list = json.loads(r['views'])
                for v in v_list: p['views'].add(str(v))
            except Exception:
                p['views'].add(str(r['views']))
        if r['impression']:
            p['impressions'].append(r['impression'])

    summary_list = []
    for pid in sorted(patients.keys()):
        p = patients[pid]
        body_str = ", ".join(sorted(p['body_parts'])) if p['body_parts'] else "Unspecified"
        views_str = ", ".join(sorted(p['views'])) if p['views'] else "AP/LAT"

        # Cross-projection hardware reconciliation
        reconciled_hw = reconcile_hardware_cross_projections(p['films'])
        hw_str = "; ".join(reconciled_hw) if reconciled_hw else "None (Intact bones)"

        # Latest or synthesized radiographic facts
        if p['impressions']:
            facts_str = f"[{p['film_count']} Films: {views_str}] " + p['impressions'][-1]
        else:
            facts_str = f"Study with {p['film_count']} films. No acute findings."

        # Use verified overrides if surgeon edited them
        active_hardware = p['verified_hardware'] if p['verified_hardware'] is not None else hw_str
        active_facts = p['verified_facts'] if p['verified_facts'] is not None else facts_str

        summary_list.append({
            'patient_id': pid,
            'name': p['name'],
            'age_sex': f"{p['age']}/{p['sex']}",
            'hospital_id': p['hospital_id'],
            'review_status': p['review_status'],
            'surgeon_notes': p['surgeon_notes'],
            'reviewed_at': p['reviewed_at'],
            'is_edited': bool(p['verified_hardware'] is not None or p['verified_facts'] is not None),
            'film_count': p['film_count'],
            'anatomy_views': f"{body_str} ({p['film_count']} films: {views_str})",
            'hardware': active_hardware,
            'hardware_list': [p['verified_hardware']] if p['verified_hardware'] is not None else reconciled_hw,
            'ai_hardware': hw_str,
            'facts': active_facts,
            'ai_facts': facts_str,
            'films': p['films']
        })
    return summary_list
