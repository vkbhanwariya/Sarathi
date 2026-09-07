"""Document page rasterization and image extraction for OCR."""

from __future__ import annotations

import io
from typing import Any, Iterator


def iter_images_from_bytes(data: bytes, dpi: int = 150) -> Iterator[Any]:
    """Yield PIL RGB images page-by-page from input bytes (PDF or Image)."""
    import pymupdf
    from PIL import Image, UnidentifiedImageError

    # 1. Check if PDF
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError):
            return

        try:
            for page in doc:
                pix = page.get_pixmap(dpi=dpi)
                yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()
        return

    # 2. Check if standard Image format (including multipage TIFF)
    try:
        from PIL import ImageOps, ImageSequence

        with Image.open(io.BytesIO(data)) as img:
            has_frames = False
            for frame in ImageSequence.Iterator(img):
                has_frames = True
                transposed = ImageOps.exif_transpose(frame)
                yield transposed.convert("RGB")
            if not has_frames:
                yield img.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return


def extract_images_from_bytes(data: bytes, dpi: int = 150) -> list[Any]:
    """Convert input file bytes (PDF or Image) into a list of PIL RGB images."""
    return list(iter_images_from_bytes(data, dpi=dpi))
