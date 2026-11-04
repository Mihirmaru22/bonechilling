"""export.py — styled Excel (.xlsx) export of the patient worklist.

Ported/rebuilt from the old import_page export: one row per patient with
reconciled cross-projection hardware, review status, surgeon notes, and a
clickable hyperlink to the patient's folder on disk.
"""
from __future__ import annotations

import io
import json
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..core.reconcile import reconcile_patient_images
from . import db as db_mod

HEADERS = [
    "Patient", "Age/Sex", "Patient ID", "Body Part(s)", "Views", "Films",
    "Hardware (reconciled)", "Impression", "Review", "Surgeon Notes", "Folder",
]
WIDTHS = [22, 9, 12, 16, 12, 6, 40, 48, 12, 30, 46]


def _views_for(images: List[dict]) -> str:
    vs = []
    for im in images:
        try:
            vs += json.loads(im.get("views") or "[]")
        except Exception:
            pass
    return ", ".join(sorted({str(v) for v in vs})) or "—"


def build_workbook(conn) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Patient Studies"

    header_fill = PatternFill("solid", fgColor="2E7DD7")
    header_font = Font(bold=True, color="FFFFFF")
    for c, (name, w) in enumerate(zip(HEADERS, WIDTHS), 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"

    r = 2
    for p in db_mod.list_patients(conn):
        images = db_mod.get_patient_images(conn, p["id"])
        body = ", ".join(sorted({im["body_part"].title() for im in images if im.get("body_part")})) or "—"

        # surgeon override wins over the AI-reconciled summary
        if p.get("verified_hardware"):
            hardware = p["verified_hardware"]
        else:
            hardware = "; ".join(reconcile_patient_images(images))
        impression = p.get("verified_facts") or next(
            (im["impression"] for im in reversed(images) if im.get("impression")), "—")

        ws.cell(row=r, column=1, value=p.get("display_name") or p.get("name") or "—")
        ws.cell(row=r, column=2, value=f"{p.get('age') or '?'}/{p.get('sex') or '?'}")
        ws.cell(row=r, column=3, value=p.get("patient_id") or "—")
        ws.cell(row=r, column=4, value=body)
        ws.cell(row=r, column=5, value=_views_for(images))
        ws.cell(row=r, column=6, value=len(images))
        ws.cell(row=r, column=7, value=hardware)
        ws.cell(row=r, column=8, value=impression)
        ws.cell(row=r, column=9, value=p.get("review_status") or "unreviewed")
        ws.cell(row=r, column=10, value=p.get("surgeon_notes") or "")
        folder = p.get("folder_path") or ""
        link = ws.cell(row=r, column=11, value=folder)
        if folder:
            link.hyperlink = "file://" + folder
            link.font = Font(color="2E7DD7", underline="single")
        for col in (7, 8, 10):
            ws.cell(row=r, column=col).alignment = Alignment(wrap_text=True, vertical="top")
        r += 1
    return wb


def export_bytes(conn) -> bytes:
    buf = io.BytesIO()
    build_workbook(conn).save(buf)
    return buf.getvalue()
