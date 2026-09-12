"""Document page rasterization and image extraction for OCR."""

from __future__ import annotations

import io
from typing import Any, Iterator


def get_page_count_from_bytes(data: bytes) -> int:
    """Return total number of pages in PDF or frames in image without rasterizing."""
    if not data:
        return 0
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            import pymupdf

            doc = pymupdf.open(stream=data, filetype="pdf")
            try:
                return len(doc)
            finally:
                doc.close()
        except Exception:
            return 0
    try:
        from PIL import Image, ImageSequence

        with Image.open(io.BytesIO(data)) as img:
            return sum(1 for _ in ImageSequence.Iterator(img)) or 1
    except Exception:
        return 0


def extract_single_page_image(
    data: bytes,
    page_number: int,
    dpi: int = 150,
    cancellation_token: Any | None = None,
) -> Any | None:
    """Extract and rasterize a single page (1-indexed) without rasterizing any other pages."""
    if cancellation_token is not None:
        cancellation_token.check_cancelled()

    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        import pymupdf
        from PIL import Image

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError):
            return None
        try:
            if page_number < 1 or page_number > len(doc):
                return None
            if cancellation_token is not None:
                cancellation_token.check_cancelled()
            page = doc[page_number - 1]
            pix = page.get_pixmap(dpi=dpi)
            return Image.frombuffer("RGB", (pix.width, pix.height), pix.samples, "raw", "RGB", 0, 1)
        finally:
            doc.close()

    try:
        from PIL import Image, ImageOps, ImageSequence

        with Image.open(io.BytesIO(data)) as img:
            for idx, frame in enumerate(ImageSequence.Iterator(img), start=1):
                if idx == page_number:
                    if cancellation_token is not None:
                        cancellation_token.check_cancelled()
                    transposed = ImageOps.exif_transpose(frame)
                    return transposed.convert("RGB")
            return None
    except Exception:
        return None


def iter_images_from_bytes(
    data: bytes,
    dpi: int = 150,
    cancellation_token: Any | None = None,
    skip_pages: set[int] | None = None,
) -> Iterator[Any]:
    """Yield PIL RGB images page-by-page from input bytes (PDF or Image) with cooperative cancellation."""
    import pymupdf
    from PIL import Image, UnidentifiedImageError

    # 1. Check if PDF
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError):
            return

        try:
            for page_idx, page in enumerate(doc, start=1):
                if cancellation_token is not None:
                    cancellation_token.check_cancelled()
                if skip_pages and page_idx in skip_pages:
                    yield None
                    continue
                pix = page.get_pixmap(dpi=dpi)
                yield Image.frombuffer("RGB", (pix.width, pix.height), pix.samples, "raw", "RGB", 0, 1)
        finally:
            doc.close()
        return

    # 2. Check if standard Image format (including multipage TIFF)
    try:
        from PIL import ImageOps, ImageSequence

        with Image.open(io.BytesIO(data)) as img:
            has_frames = False
            for page_idx, frame in enumerate(ImageSequence.Iterator(img), start=1):
                has_frames = True
                if cancellation_token is not None:
                    cancellation_token.check_cancelled()
                if skip_pages and page_idx in skip_pages:
                    yield None
                    continue
                transposed = ImageOps.exif_transpose(frame)
                yield transposed.convert("RGB")
            if not has_frames:
                if cancellation_token is not None:
                    cancellation_token.check_cancelled()
                yield img.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return


def extract_images_from_bytes(
    data: bytes,
    dpi: int = 150,
    cancellation_token: Any | None = None,
    skip_pages: set[int] | None = None,
) -> list[Any]:
    """Convert input file bytes (PDF or Image) into a list of PIL RGB images."""
    return list(iter_images_from_bytes(data, dpi=dpi, cancellation_token=cancellation_token, skip_pages=skip_pages))
