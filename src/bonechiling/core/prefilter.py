"""prefilter.py — ultra-fast heuristic to skip obvious non-X-rays.

Moved out of vision.py. This is only a *cheap first pass*: the VLM's
`image_type` is the final authority (see pipeline). When the heuristic is
unsure it returns ``MAYBE`` so the caller still runs the model rather than
silently dropping a borderline film (one real film photo in the test set
scored 26.1 against the old hard cutoff of 28).
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Union

from PIL import Image, ImageStat


class PrefilterVerdict(str, Enum):
    XRAY = "xray"          # confidently radiograph-like
    NON_XRAY = "non_xray"  # confidently not a radiograph (color photo / white document)
    MAYBE = "maybe"        # ambiguous -> let the VLM decide


# Tunable thresholds (documented so the eval harness can sweep them).
COLOR_DIFF_STRONG = 45.0   # clearly a color photo above this
COLOR_DIFF_SOFT = 22.0     # clearly grayscale below this
WHITE_RATIO_DOC = 0.72     # mostly-white page => document
DARK_RATIO_MIN = 0.06      # radiographs have a meaningful dark region


def classify(image_path: Union[str, Path]) -> PrefilterVerdict:
    """Return XRAY / NON_XRAY / MAYBE for a path. Never raises."""
    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            stat = ImageStat.Stat(rgb)
            r, g, b = stat.mean
            color_diff = (abs(r - g) + abs(g - b) + abs(b - r)) / 3.0

            gray = img.convert("L")
            hist = gray.histogram()
            total = sum(hist) or 1
            white_ratio = sum(hist[215:]) / total
            dark_ratio = sum(hist[:70]) / total

        # Strongly colored -> wound/skin/clinical photo.
        if color_diff > COLOR_DIFF_STRONG:
            return PrefilterVerdict.NON_XRAY
        # Mostly white with little dark area -> paper document / prescription.
        if white_ratio > WHITE_RATIO_DOC and dark_ratio < DARK_RATIO_MIN:
            return PrefilterVerdict.NON_XRAY
        # Grayscale with a real dark region -> looks like a radiograph.
        if color_diff < COLOR_DIFF_SOFT and dark_ratio >= DARK_RATIO_MIN:
            return PrefilterVerdict.XRAY
        return PrefilterVerdict.MAYBE
    except Exception:
        return PrefilterVerdict.MAYBE


def is_likely_xray(image_path: Union[str, Path]) -> bool:
    """Backward-compatible boolean: only a confident NON_XRAY is skipped."""
    return classify(image_path) != PrefilterVerdict.NON_XRAY
