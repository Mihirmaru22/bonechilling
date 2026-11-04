"""imaging.py — shared image helpers (encode/downscale).

Film detection + perspective warp (OpenCV) will be added here in a later phase;
for now this handles the downscale + base64 encoding every engine needs.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Tuple, Union

from PIL import Image

DEFAULT_MAX_SIZE = 1536  # a bit larger than the old 1280 so label text survives


def load_rgb(image_path: Union[str, Path]) -> Image.Image:
    img = Image.open(image_path)
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
    img = image if isinstance(image, Image.Image) else Image.open(image)
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
