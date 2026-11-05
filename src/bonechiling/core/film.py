"""film.py — find the X-ray film inside a phone photo and straighten it.

Why: every sample image is a 4000x3000 phone photo of a film, often tilted,
on a light box or held against a window. The printed label band is on the film,
somewhere mid-frame — not at the edge of the photo. Reading "the bottom 15% of
the photo" misses it. This module locates the bright film quadrilateral and
perspective-warps it to a flat rectangle, so OCR and the VLM see the film, not
the whole room.

Degrades safely: if no confident film is found, returns the original image with
found=False, and the caller just uses the whole photo (old behavior).

Benchmark note (2026-11-04, 19 sample photos): detection fires on all 19, and
the straightened crop clearly helps some labels (e.g. 'I SOLANKI' -> full name)
but hurts others, so it is NOT a net win for Tesseract on its own. The pipeline
therefore keeps the BEST of raw-vs-crop OCR rather than trusting the crop, and
the crop's main intended payoff is feeding the VLM a clean film (to be measured
with a live engine). Full-film warp + band-read could be refined to deskew-only.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np
from PIL import Image

ImageOrPath = Union[str, Path, Image.Image]

# A real film should occupy a decent chunk of the frame; below this we don't
# trust the detection and fall back to the whole image.
MIN_AREA_FRACTION = 0.12
WORK_SIZE = 1600  # detection runs on a downscaled copy for speed


@dataclass
class FilmDetection:
    image: Image.Image     # warped film (or original on failure)
    found: bool
    area_fraction: float = 0.0


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGB"))[:, :, ::-1].copy()  # RGB->BGR


def _cv_to_pil(arr: np.ndarray) -> Image.Image:
    return Image.fromarray(arr[:, :, ::-1])  # BGR->RGB


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = pts.reshape(4, 2).astype("float32")
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)
    return np.array([
        pts[np.argmin(s)],   # tl
        pts[np.argmin(d)],   # tr
        pts[np.argmax(s)],   # br
        pts[np.argmax(d)],   # bl
    ], dtype="float32")


def _warp(cv_img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    import cv2

    tl, tr, br, bl = corners
    w = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
    h = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
    w, h = max(w, 1), max(h, 1)
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(cv_img, M, (w, h))


def extract_film(image: ImageOrPath) -> FilmDetection:
    """Detect and straighten the film. Never raises."""
    import cv2

    try:
        pil = image if isinstance(image, Image.Image) else Image.open(image)
        pil = pil.convert("RGB")
    except Exception:
        # Can't even open it — hand back a blank; caller handles found=False.
        return FilmDetection(image=Image.new("RGB", (1, 1)), found=False)

    full = _pil_to_cv(pil)
    H, W = full.shape[:2]
    scale = min(1.0, WORK_SIZE / max(H, W))
    work = cv2.resize(full, (int(W * scale), int(H * scale))) if scale < 1.0 else full.copy()

    try:
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        # Film is the bright region against a darker surround -> Otsu.
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE,
                                  cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15)))
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return FilmDetection(image=pil, found=False)

        work_area = work.shape[0] * work.shape[1]
        biggest = max(contours, key=cv2.contourArea)
        area_frac = cv2.contourArea(biggest) / float(work_area)
        if area_frac < MIN_AREA_FRACTION:
            return FilmDetection(image=pil, found=False, area_fraction=area_frac)

        # Try to approximate a 4-corner quad; else use the min-area rect.
        peri = cv2.arcLength(biggest, True)
        approx = cv2.approxPolyDP(biggest, 0.02 * peri, True)
        if len(approx) == 4:
            corners = _order_corners(approx.astype("float32"))
        else:
            box = cv2.boxPoints(cv2.minAreaRect(biggest))
            corners = _order_corners(box)

        corners = corners / scale  # map back to full-resolution coordinates
        warped = _warp(full, corners)
        return FilmDetection(image=_cv_to_pil(warped), found=True, area_fraction=area_frac)
    except Exception:
        return FilmDetection(image=pil, found=False)
