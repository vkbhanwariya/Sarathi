"""OCR-specific typography helpers.

Shared output font selection and size normalization live in ``sarathi.shakti.text.typography``.
This module owns only OCR line-height inference while retaining the existing OCR imports.
"""

from __future__ import annotations

from sarathi.shakti.text.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    contains_devanagari,
    normalize_size,
    output_font,
)


def infer_line_font_size(
    bbox: tuple[float, float, float, float] | None,
    *,
    median_line_height: float | None = None,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> tuple[float, bool]:
    """Infer proportional font size and heading status from bounding-box height."""
    if not bbox or len(bbox) < 4:
        return default_size_pt, False

    line_height = abs(bbox[3] - bbox[1])
    if line_height <= 0:
        return default_size_pt, False

    if median_line_height and median_line_height > 0:
        ratio = line_height / median_line_height
        if ratio >= 1.6:
            return 18.0, True
        if ratio >= 1.3:
            return 15.0, True
        if ratio <= 0.8:
            return 10.0, False

    return default_size_pt, False


__all__ = [
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "ENGLISH_FONT",
    "contains_devanagari",
    "infer_line_font_size",
    "normalize_size",
    "output_font",
]
