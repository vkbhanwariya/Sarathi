"""Document page rasterization and image extraction for OCR."""

from __future__ import annotations

import io
import threading
from typing import Any, Iterator

_PYMUPDF_LOCK = threading.Lock()


def get_page_count_from_bytes(data: bytes) -> int:
    """Return total number of pages in PDF or frames in image without rasterizing."""
    if not data:
        return 0
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            import pymupdf

            with _PYMUPDF_LOCK:
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

        with _PYMUPDF_LOCK:
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
        with _PYMUPDF_LOCK:
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


class BoundedPageRasterizer:
    """Pre-rasterizes document pages sequentially into a bounded memory queue using a single open document.

    Overlaps CPU rasterization of upcoming pages with active OCR inference while bounding memory
    to `max_buffered` pages (default 4). Opens PDF/Image stream exactly once.
    """

    def __init__(
        self,
        data: bytes,
        pages: list[int] | None = None,
        dpi: int = 150,
        max_buffered: int = 4,
        cancellation_token: Any | None = None,
    ) -> None:
        self._data = data
        self._pages = pages
        self._dpi = dpi
        self._max_buffered = max(1, max_buffered)
        self._cancellation_token = cancellation_token

        self._ready_pages: dict[int, Any] = {}
        self._errors: dict[int, Exception] = {}
        self._cond = threading.Condition()
        self._closed = False
        self._producer_thread: threading.Thread | None = None

    def start(self) -> BoundedPageRasterizer:
        """Start the background pre-rasterization worker thread."""
        with self._cond:
            if self._producer_thread is not None:
                return self
            self._producer_thread = threading.Thread(
                target=self._producer_worker,
                daemon=True,
                name="sarathi-page-rasterizer",
            )
            self._producer_thread.start()
            return self

    def __enter__(self) -> BoundedPageRasterizer:
        return self.start()

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Stop background rasterization worker and clear buffered images."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        if self._producer_thread is not None and self._producer_thread.is_alive():
            self._producer_thread.join(timeout=2.0)
        with self._cond:
            self._ready_pages.clear()

    def get_page(self, page_number: int) -> Any | None:
        """Retrieve the rasterized PIL Image for the specified 1-indexed page number.

        Blocks until the page has been rasterized or rasterization fails.
        Releases buffer space so subsequent pages can be rasterized.
        """
        with self._cond:
            while page_number not in self._ready_pages and page_number not in self._errors and not self._closed:
                if self._cancellation_token is not None and self._cancellation_token.is_cancelled:
                    self._cancellation_token.check_cancelled()
                self._cond.wait(timeout=0.2)

            if page_number in self._errors:
                raise self._errors[page_number]

            if page_number in self._ready_pages:
                img = self._ready_pages.pop(page_number)
                self._cond.notify_all()
                return img

            return None

    def _producer_worker(self) -> None:
        """Producer loop running in background thread: opens stream once and yields pages."""
        try:
            if not self._data:
                return

            total_pages = get_page_count_from_bytes(self._data)
            skip_pages: set[int] | None = None
            if self._pages is not None:
                needed_set = set(self._pages)
                skip_pages = set(p for p in range(1, total_pages + 1) if p not in needed_set)

            page_iter = iter_images_from_bytes(
                self._data,
                dpi=self._dpi,
                cancellation_token=self._cancellation_token,
                skip_pages=skip_pages,
            )

            for page_idx, img in enumerate(page_iter, start=1):
                if img is None:
                    continue

                with self._cond:
                    while len(self._ready_pages) >= self._max_buffered and not self._closed:
                        self._cond.wait(timeout=0.1)
                    if self._closed:
                        break

                if self._cancellation_token is not None and self._cancellation_token.is_cancelled:
                    break

                with self._cond:
                    self._ready_pages[page_idx] = img
                    self._cond.notify_all()

        except Exception as exc:
            with self._cond:
                if self._pages:
                    for p in self._pages:
                        if p not in self._ready_pages:
                            self._errors[p] = exc
                self._closed = True
                self._cond.notify_all()
        finally:
            with self._cond:
                self._closed = True
                self._cond.notify_all()


__all__ = [
    "BoundedPageRasterizer",
    "extract_images_from_bytes",
    "extract_single_page_image",
    "get_page_count_from_bytes",
    "iter_images_from_bytes",
]
