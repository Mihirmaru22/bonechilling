"""reconcile.py — cross-projection orthopedic hardware reconciliation.

Ported out of the old monolithic db.py. When the same implant is seen on
orthogonal projections (AP + LAT) it is the SAME physical construct, not two —
this groups per-image hardware into one deduplicated, human-readable summary and
notes when presence is confirmed across orthogonal views.

Accepts hardware as a JSON string, a list of dicts (new schema), or a list of
free-text strings (older/looser model output).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def normalize_text(text: Any) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip().lower())


def parse_views(views_raw: Any) -> set:
    if not views_raw:
        return set()
    s = str(views_raw)
    if s.startswith("["):
        try:
            s = " ".join(str(x) for x in json.loads(s))
        except Exception:
            pass
    u = s.upper()
    found = set()
    if "AP" in u or "ANTEROPOST" in u:
        found.add("AP")
    if "PA" in u or "POSTEROANT" in u:
        found.add("PA")
    if "LAT" in u or "LATERAL" in u:
        found.add("LAT")
    if "MORTISE" in u:
        found.add("MORTISE")
    if "OBLIQUE" in u:
        found.add("OBLIQUE")
    if "AXIAL" in u:
        found.add("AXIAL")
    return found


def are_orthogonal(views: set) -> bool:
    return bool(views & {"AP", "PA"}) and bool(views & {"LAT"})


def categorize_implant(text: str):
    t = normalize_text(text)
    if "k-wire" in t or "kwire" in t or "kirschner" in t:
        return "k_wire", "K-wires"
    if "plate" in t or "dcp" in t or "lcp" in t:
        return "plate", "plate"
    if "nail" in t or "rod" in t or "intramedullary" in t:
        return "nail", "nail"
    if "screw" in t:
        return "screw", "screws"
    if any(w in t for w in ("total hip", "replacement", "stem", "prosthesis", "arthroplasty")):
        return "arthroplasty", "arthroplasty"
    if "wire" in t or "cerclage" in t or "tension band" in t:
        return "wire", "wire"
    return "other", str(text).strip()


_LOCATIONS = [
    "medial condyle", "lateral condyle", "femoral neck", "femoral head",
    "distal femur", "proximal femur", "femur", "olecranon", "radial head",
    "distal radius", "radius", "ulna", "medial malleolus", "lateral malleolus",
    "distal tibia", "proximal tibia", "tibia", "fibula", "acetabulum", "pelvis",
    "greater trochanter", "lesser trochanter", "humeral head", "glenoid",
    "clavicle", "patella",
]


def extract_location(text: str) -> str:
    t = normalize_text(text)
    for loc in _LOCATIONS:
        if loc in t:
            return loc
    return ""


def parse_single_hardware_item(item: Any):
    if isinstance(item, dict):
        imp = item.get("implant", "")
        loc = item.get("location", "")
        count = item.get("count", 1)
        integrity = item.get("integrity", "intact")
        cat, std = categorize_implant(imp)
        return {
            "implant_category": cat, "display_name": imp or std,
            "location": normalize_text(loc) or extract_location(imp),
            "count": int(count) if count else 1,
            "secondary_count": None, "secondary_name": None,
            "integrity": normalize_text(integrity) or "intact",
        }
    s = str(item).strip()
    if not s or s.lower() in ("none", "[]", "null"):
        return None
    integrity = "intact"
    m = re.search(r"\(([^)]+)\)", s)
    if m:
        txt = m.group(1).lower()
        if any(w in txt for w in ("loose", "displace", "break", "broke", "fail")):
            integrity = txt
        s = (s[: m.start()] + s[m.end():])
    sec_count = sec_name = None
    ms = re.search(r"with\s+(\d+)?\s*([a-zA-Z\s\-]+screws?)", s, re.I)
    if ms:
        sec_count = int(ms.group(1)) if ms.group(1) else 1
        sec_name = ms.group(2).strip()
    mc = re.match(r"\s*(\d+)\s*[.\-]?\s*", s)
    count = int(mc.group(1)) if mc else 1
    remainder = s[mc.end():].strip() if mc else s.strip()
    cat, std = categorize_implant(remainder)
    title = re.sub(r"^(at|in|on|with)\s+", "", remainder, flags=re.I).split(" at ")[0].strip()
    return {
        "implant_category": cat, "display_name": title or std,
        "location": extract_location(remainder), "count": count,
        "secondary_count": sec_count, "secondary_name": sec_name, "integrity": integrity,
    }


def _hardware_items(raw: Any) -> List[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("["):
            try:
                return json.loads(raw)
            except Exception:
                return [raw]
        return [raw] if raw else []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    return [raw]


def reconcile_hardware(films: List[Dict]) -> List[str]:
    """films: dicts with 'views', 'body_part', 'hardware'. Returns summary lines."""
    groups: List[Dict] = []
    for f in films:
        views = parse_views(f.get("views", ""))
        body = normalize_text(f.get("body_part", ""))
        for it in _hardware_items(f.get("hardware")):
            p = parse_single_hardware_item(it)
            if not p:
                continue
            match = None
            for g in groups:
                if g["implant_category"] != p["implant_category"]:
                    continue
                loc_ok = (g["location"] == p["location"] or not g["location"] or not p["location"]
                          or g["location"] in p["location"] or p["location"] in g["location"])
                bp_ok = (g["body_part"] == body or not g["body_part"] or not body
                         or g["body_part"] in body or body in g["body_part"])
                if loc_ok and bp_ok:
                    match = g
                    break
            if match:
                match["views"].update(views)
                match["counts"].append(p["count"])
                if p["secondary_count"]:
                    match["secondary_counts"].append(p["secondary_count"])
                if not match["location"] and p["location"]:
                    match["location"] = p["location"]
                if len(p["display_name"]) > len(match["display_name"]):
                    match["display_name"] = p["display_name"]
            else:
                groups.append({
                    "implant_category": p["implant_category"], "display_name": p["display_name"],
                    "location": p["location"], "body_part": body, "views": set(views),
                    "counts": [p["count"]],
                    "secondary_counts": [p["secondary_count"]] if p["secondary_count"] else [],
                    "secondary_name": p["secondary_name"], "integrity": p["integrity"],
                })
    if not groups:
        return ["No orthopaedic implants or surgical hardware identified."]

    out = []
    for g in groups:
        count = max(g["counts"]) if g["counts"] else 1
        vlist = sorted(g["views"])
        if are_orthogonal(g["views"]):
            vnote = "confirmed on orthogonal AP/LAT views"
        elif len(g["views"]) > 1:
            vnote = f"confirmed across {'/'.join(vlist)} views"
        elif g["views"]:
            vnote = f"{'/'.join(vlist)} view"
        else:
            vnote = ""
        name = g["display_name"]
        if not re.match(r"^\d+", name):
            label = f"{count} {name}" + ("s" if count > 1 and not name.lower().endswith("s") else "")
        else:
            label = re.sub(r"^\d+", str(count), name)
        parts = [label]
        if g["secondary_counts"] and g["secondary_name"]:
            parts.append(f"with {max(g['secondary_counts'])} {g['secondary_name']}")
        if g["location"] and g["location"] not in name.lower():
            parts.append(f"at {g['location']}")
        status = [g["integrity"] if g["integrity"] and g["integrity"] != "intact" else "intact"]
        if vnote:
            status.append(vnote)
        out.append(f"{' '.join(parts)} ({', '.join(status)})")
    return out


def reconcile_patient_images(images: List[Dict]) -> List[str]:
    """Adapter for new-schema image rows (keys: views, body_part, hardware)."""
    return reconcile_hardware([
        {"views": im.get("views"), "body_part": im.get("body_part"), "hardware": im.get("hardware")}
        for im in images
    ])
