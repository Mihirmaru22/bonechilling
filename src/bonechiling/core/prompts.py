"""prompts.py — the single source of truth for what we ask the vision model.

Shared across every engine so local and cloud get an identical instruction set
(the only thing that changes is the provider transport). Objective-facts-only.
"""
from __future__ import annotations

from .schema import XrayFacts

SYSTEM_PROMPT = (
    "You are an objective radiographic fact extractor for orthopedic clinical records. "
    "You DO NOT diagnose diseases, suggest causes, or speculate. You state only strictly "
    "verifiable facts visible in the image. You also read any printed patient label text. "
    "You always return a single valid JSON object and nothing else."
)


def build_user_prompt() -> str:
    """User instruction with the schema hint inlined (helps small models)."""
    return (
        "Extract strictly verifiable radiographic facts from this image for a physician.\n"
        "Do NOT give clinical diagnoses or speculative interpretations.\n\n"
        "If the image is NOT a medical X-ray (a document, prescription, ID card, or a photo "
        'of a person/wound), return {"image_type": "Non-X-ray", "body_part": null, '
        '"impression": "Non-X-ray image"} and leave other fields empty.\n\n'
        "Otherwise return JSON with EXACTLY these fields and nothing else:\n"
        f"{XrayFacts.json_schema_hint()}\n\n"
        "Field rules:\n"
        "- views: projections visible (AP, PA, LAT, OBLIQUE, MORTISE, AXIAL).\n"
        "- hardware: each implant as an object with implant, location, count, integrity. "
        "Report counts and integrity you can actually see; empty list if none.\n"
        "- visible_findings: only observable facts about bone alignment, cortical continuity, "
        "and joint spaces. No diagnoses.\n"
        "- impression: one factual sentence summarizing anatomy, projections, hardware, and "
        "alignment status. Not a diagnosis.\n"
        "- label: read the printed text band on the film (patient name, age, sex, id, date, "
        "hospital). Use null for anything not clearly legible. Never invent values.\n"
        "- confidence: your honest 0..1 confidence in the extraction.\n"
    )


USER_PROMPT = build_user_prompt()
