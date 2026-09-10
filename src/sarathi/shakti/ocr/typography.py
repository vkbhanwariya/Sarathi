"""Mini typography helper for OCR capability in Sarathi.

Owns recognized-output DOCX typography:
- English-only -> Times New Roman
- Hindi / Hindi-English mixed -> Nirmala UI
- Preserves reliable source size or falls back to canonical default (12 pt).

Does not own legacy font conversion, calibration tables, or OpenXML serialization.
"""

from __future__ import annotations

import re

ENGLISH_FONT: str = "Times New Roman"
DEVANAGARI_FONT: str = "Nirmala UI"
DEFAULT_SIZE_PT: float = 12.0

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")


def contains_devanagari(text: str) -> bool:
    """Check whether text contains any Devanagari script characters."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_DEVANAGARI_RE.search(text))


def output_font(*, contains_devanagari: bool) -> str:
    """Resolve output font family based on whether content contains Devanagari."""
    return DEVANAGARI_FONT if contains_devanagari else ENGLISH_FONT


def normalize_size(
    size_pt: float | None,
    *,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> float:
    """Preserve reliable inferred size, or fall back to canonical default."""
    eff_size = default_size_pt if size_pt is None else float(size_pt)
    if eff_size <= 0:
        raise ValueError("font size must be greater than zero")
    return eff_size


def infer_line_font_size(
    bbox: tuple[float, float, float, float] | None,
    *,
    median_line_height: float | None = None,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> tuple[float, bool]:
    """Infer proportional font size and heading status from bounding box height.

    Returns:
        tuple of (font_size_pt, is_heading)
    """
    if not bbox or len(bbox) < 4:
        return default_size_pt, False

    line_height = abs(bbox[3] - bbox[1])
    if line_height <= 0:
        return default_size_pt, False

    if median_line_height and median_line_height > 0:
        ratio = line_height / median_line_height
        if ratio >= 1.6:
            return 18.0, True  # Title / Major Heading
        elif ratio >= 1.3:
            return 15.0, True  # Section Heading
        elif ratio <= 0.8:
            return 10.0, False  # Small text / footnote
        return default_size_pt, False

    return default_size_pt, False

