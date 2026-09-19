"""Canonical page and document usability arbitration logic shared across Shakti capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sarathi.sankalpa import CanonicalDocument, PageData


def is_usable_page(page: PageData) -> bool:
    """Check whether a PageData contains usable text or table data.

    Arbitrates hybrid scanned pages and corrupted text layers:
    - If page is explicitly flagged as a scanned image, requires OCR.
    - If text is empty and there are no tables, requires OCR.
    - If native text contains excessive corruption (>= 5% replacement characters '\ufffd'
      or unprintable control codes), the text layer is deemed unusable and requires OCR.
    - If high image coverage (>= 0.75):
      - Sparse text (< 30 characters) requires OCR.
      - Header/footer only (body_char_count == 0 while headers/footers exist) requires OCR.
      - Text spans strictly confined to outer margins (y < 15% or y > 85% of page height) requires OCR.
    - Legitimate short native pages (without high image coverage) are preserved as usable native text.
    """
    if page.metadata.get("is_scanned_image"):
        return False

    p_text = page.text.strip() if page.text else ""
    p_tables = any(len(t.rows) > 0 or len(t.headers) > 0 for t in page.tables)

    if not p_text and not p_tables:
        return False

    # Text corruption check: replacement characters or non-whitespace control codes
    if p_text:
        char_count = len(p_text)
        if (p_text.count("\ufffd") / char_count) >= 0.05:
            return False
        ctrl_count = sum(1 for c in p_text if ord(c) < 32 and c not in ("\n", "\r", "\t"))
        if (ctrl_count / char_count) >= 0.05:
            return False

    # High image coverage arbitration
    img_cov = page.metadata.get("image_coverage", 0.0)
    if isinstance(img_cov, (int, float)) and img_cov >= 0.75:
        # 1. Sparse overall text
        if len(p_text) < 30:
            return False

        # 2. Header/footer only text (scanned body)
        body_chars = page.metadata.get("body_char_count")
        if body_chars is not None and body_chars == 0 and (page.metadata.get("header") or page.metadata.get("footer")):
            return False

        # 3. Spatial margin confinement check on spans
        if page.spans and not p_tables:
            page_h = page.metadata.get("page_height") or page.metadata.get("height")
            if page_h and page_h > 0:
                top_margin = 0.15 * page_h
                bottom_margin = 0.85 * page_h
                has_body_span = any(
                    s.bounding_box is not None and (s.bounding_box[1] < bottom_margin and s.bounding_box[3] > top_margin)
                    for s in page.spans
                )
                if not has_body_span:
                    return False

    return bool(p_text) or p_tables


def is_usable_document(doc: CanonicalDocument) -> bool:
    """Check whether a CanonicalDocument contains usable text or table data across all pages."""
    if doc.pages:
        return all(is_usable_page(p) for p in doc.pages)
    has_text = bool(doc.text and doc.text.strip())
    has_tables = any(len(t.rows) > 0 or len(t.headers) > 0 for t in doc.tables)
    return has_text or has_tables


__all__ = [
    "is_usable_document",
    "is_usable_page",
]
