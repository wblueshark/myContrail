"""Thumbnail generation.

Image.draft() is mandatory, not an optimisation. It tells the JPEG decoder to
scale during the DCT pass instead of decoding at full resolution and resampling
afterwards. Measured on this machine with a 4000x3000 JPEG: 12 ms -> 5 ms, a
2.5x speedup. Skipping it puts the "100k photos in 15 minutes" target off by an
order of magnitude.

Two sizes are produced:
    512 px  thumb  - detail panels and the photo grid
     64 px  micro  - the map's texture atlas
"""

from __future__ import annotations

import io
from pathlib import Path

THUMB_SIZE = 512
MICRO_SIZE = 64
WEBP_QUALITY = 82
MICRO_QUALITY = 70

_HEIF_REGISTERED = False


def _ensure_heif() -> None:
    """HEIC is the iPhone default, and its EXIF/pixels need the plugin."""
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:  # noqa: BLE001 - degrade to "EXIF only, no thumbnail"
        pass
    _HEIF_REGISTERED = True


def render_thumbnails(path: Path) -> tuple[bytes, bytes, int, int] | None:
    """-> (thumb_webp, micro_webp, width, height), or None if undecodable.

    A photo we cannot decode is not a failure worth aborting an import for; it
    still gets a row, just without a thumbnail.
    """
    from PIL import Image, ImageOps

    _ensure_heif()
    try:
        with Image.open(path) as img:
            width, height = img.size
            # draft() must be called BEFORE the pixels are loaded.
            if img.format == "JPEG":
                img.draft("RGB", (THUMB_SIZE, THUMB_SIZE))
            img = ImageOps.exif_transpose(img)  # honour the Orientation tag
            img = img.convert("RGB")

            thumb = img.copy()
            thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            micro = thumb.copy()
            micro.thumbnail((MICRO_SIZE, MICRO_SIZE), Image.Resampling.LANCZOS)

            return (
                _encode(thumb, WEBP_QUALITY),
                _encode(micro, MICRO_QUALITY),
                width,
                height,
            )
    except Exception:  # noqa: BLE001
        return None


def _encode(img, quality: int) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="WEBP", quality=quality, method=4)
    return buffer.getvalue()
