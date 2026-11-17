"""imaging.py — shared image helpers (encode/downscale).

Film detection + perspective warp (OpenCV) will be added here in a later phase;
for now this handles the downscale + base64 encoding every engine needs.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Tuple, Union

from PIL import Image, ImageOps

DEFAULT_MAX_SIZE = 1536  # a bit larger than the old 1280 so label text survives


def open_image(image_path: Union[str, Path]) -> Image.Image:
    """Open an image the way a person would see it.

    * Applies the EXIF orientation tag, so a phone photo taken in portrait is
      not handed to OCR / the model lying on its side.
    * Scales 16/32-bit greyscale (common in PNG/TIFF exports of radiographs) to
      8-bit; a plain convert() would clip them to almost pure white.
    * Takes the first frame of multi-page TIFFs.
    The returned image is fully loaded, so the file handle is already closed.
    """
    with Image.open(image_path) as src:
        try:
            src.seek(0)
        except (EOFError, AttributeError):
            pass
        img = ImageOps.exif_transpose(src) or src
        img.load()
        if img.mode in ("I;16", "I;16B", "I;16L", "I", "F"):
            import numpy as np
            arr = np.asarray(img, dtype=np.float64)
            lo, hi = float(arr.min()), float(arr.max())
            arr = (arr - lo) * (255.0 / (hi - lo)) if hi > lo else arr * 0
            img = Image.fromarray(arr.clip(0, 255).astype("uint8"), mode="L")
        elif img.mode in ("RGBA", "LA", "P", "PA"):
            img = img.convert("RGB")
        return img.copy() if img is src else img


def load_rgb(image_path: Union[str, Path]) -> Image.Image:
    img = open_image(image_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def encode_jpeg_b64(
    image: Union[str, Path, Image.Image],
    max_size: int = DEFAULT_MAX_SIZE,
    quality: int = 90,
) -> Tuple[str, str]:
    """Return (base64_str, mime_type) for an image path or PIL image.

    Large phone photos are downscaled so the model context does not explode,
    but not so far that printed label text becomes unreadable.
    """
    img = image if isinstance(image, Image.Image) else open_image(image)
    try:
        if max(img.size) > max_size:
            img = img.copy()
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"
    finally:
        if not isinstance(image, Image.Image):
            img.close()
