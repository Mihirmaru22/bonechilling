"""normalize.py — turns messy OCR lines into clean, typed fields."""
import json
import re
import sys
from pathlib import Path

from ocr import ocr_lines          # first time one of our files uses another!

# Your real OCR output, frozen as a test case forever:
SAMPLE_LINES = [
    "Elbow AP/LAT 02/01/2026 10:28:41 AM Elbow AP/LAT 02/01/2026 10:29:32 AM",
    "H.J. DOSHI SARVAJANIK HOSPITAL, RAJKOT.",
    "KARSHANBHAI BHARVAD 35 year(s) / Male 020110",
]

DATETIME_RE = re.compile(r"\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*[AP]M")
VIEW_RE     = re.compile(r"\b(AP|PA|LAT|LATERAL|OBLIQUE)\b")
BODY_RE     = re.compile(r"\b(elbow|chest|wrist|knee|shoulder|ankle|hand|foot|"
                         r"hip|pelvis|spine|skull|forearm|humerus|femur|femer|tibia|"
                         r"fibula|clavicle)\b", re.I)
PERSON_RE   = re.compile(
    r"(?P<name>.+?)\s+(?P<age>\d{1,3})\s*year\(s\)?\s*/\s*(?P<sex>male|female)"
    r"(?:\s+(?P<rest>\S+))?",
    re.I,
)


def normalize(lines):
    out = {
        "name": None, "age": None, "sex": None,
        "accession_or_id": None,
        "hospital": None,
        "body_part": None,
        "views": [],
        "timestamps": [],
        "study_date_raw": None,
        "study_date": None,
        "warnings": [],
    }
    text = "\n".join(lines)

    # --- timestamps & date ---
    out["timestamps"] = DATETIME_RE.findall(text)
    if out["timestamps"]:
        out["study_date_raw"] = out["timestamps"][0].split()[0]
        d, m, y = out["study_date_raw"].split("/")
        out["study_date"] = f"{y}-{m}-{d}"          # assume DD/MM/YYYY
        out["warnings"].append("date format assumed DD/MM/YYYY")
    if len(out["timestamps"]) > 1:
        out["warnings"].append(
            f"{len(out['timestamps'])} timestamps found; kept first as study date")

    # --- views & body part (dedupe keeps order) ---
    for v in VIEW_RE.findall(text):
        if v not in out["views"]:
            out["views"].append(v)
    bm = BODY_RE.search(text)
    if bm:
        bp = bm.group(0).lower()
        out["body_part"] = "femur" if bp == "femer" else bp
    else:
        out["body_part"] = None

    # --- hospital ---
    for line in lines:
        if "hospital" in line.lower():
            out["hospital"] = line.strip(" |-_.,:;~'")
            break

    # --- person line ---
    for line in lines:
        pm = PERSON_RE.search(line)
        if pm:
            clean_name = pm.group("name").strip(" |-_.,:;~'")
            out["name"] = clean_name
            out["age"] = pm.group("age")
            out["sex"] = "M" if pm.group("sex").lower() == "male" else "F"
            rest = pm.group("rest")
            if rest and rest.isdigit():
                out["accession_or_id"] = rest
                out["warnings"].append(
                    "numeric code stored as accession_or_id; may be patient id")
            break

    if out["name"] is None:
        out["warnings"].append("no person line found")
    return out


if __name__ == "__main__":
    # SELF-TEST: python normalize.py            -> uses frozen sample lines
    #            python normalize.py img.jpg    -> uses live OCR
    lines = ocr_lines(Path(sys.argv[1])) if len(sys.argv) > 1 else SAMPLE_LINES
    print(json.dumps(normalize(lines), indent=2))