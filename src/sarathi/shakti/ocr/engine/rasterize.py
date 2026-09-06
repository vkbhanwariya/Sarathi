"""Document page rasterization and image extraction for OCR."""

from __future__ import annotations

import io
from typing import Any


def extract_images_from_bytes(data: bytes) -> list[Any]:
    """Convert input file bytes (PDF or Image) into a list of PIL RGB images."""
    import pymupdf
    from PIL import Image, UnidentifiedImageError

    # 1. Check if PDF
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError):
            return []

        images = []
        try:
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                images.append(img)
        finally:
            doc.close()
        return images

    # 2. Check if standard Image format (including multipage TIFF)
    try:
        from PIL import ImageOps, ImageSequence

        with Image.open(io.BytesIO(data)) as img:
            images = []
            for frame in ImageSequence.Iterator(img):
                transposed = ImageOps.exif_transpose(frame)
                images.append(transposed.convert("RGB"))
            return images if images else [img.convert("RGB")]
    except (UnidentifiedImageError, OSError, ValueError):
        return []
