"""Mini typography helper for Translation capability in Sarathi V2.

Owns translated-output DOCX typography:
- English-only -> Times New Roman
- Hindi / Hindi-English mixed -> Nirmala UI
- Preserves source logical font size.

Does not own legacy font conversion, calibration tables, or OpenXML serialization.
"""

from __future__ import annotations

import re

ENGLISH_FONT: str = "Times New Roman"
DEVANAGARI_FONT: str = "Nirmala UI"

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")


def contains_devanagari(text: str) -> bool:
    """Check whether text contains any Devanagari script characters."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_DEVANAGARI_RE.search(text))


def output_font(*, contains_devanagari: bool) -> str:
    """Resolve output font family based on whether content contains Devanagari."""
    return DEVANAGARI_FONT if contains_devanagari else ENGLISH_FONT


DEFAULT_SIZE_PT: float = 12.0


def normalize_size(
    size_pt: float | None = None,
    *,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> float:
    """Validate and preserve source logical font size, falling back to default."""
    eff_size = default_size_pt if size_pt is None else float(size_pt)
    if eff_size <= 0:
        raise ValueError("font size must be greater than zero")
    return eff_size

