"""Shared output typography primitives for Shakti document capabilities."""

from __future__ import annotations

import re

ENGLISH_FONT: str = "Times New Roman"
DEVANAGARI_FONT: str = "Nirmala UI"
DEFAULT_SIZE_PT: float = 12.0

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")
DEVANAGARI_RE = _DEVANAGARI_RE


def contains_devanagari(text: str) -> bool:
    """Return whether text contains any Devanagari-script character."""
    if not isinstance(text, str) or not text:
        return False
    return bool(_DEVANAGARI_RE.search(text))


def output_font(*, contains_devanagari: bool) -> str:
    """Choose the canonical output font for Latin-only or Devanagari content."""
    return DEVANAGARI_FONT if contains_devanagari else ENGLISH_FONT


def normalize_size(
    size_pt: float | None = None,
    *,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> float:
    """Preserve a positive logical font size or use the canonical default."""
    eff_size = default_size_pt if size_pt is None else float(size_pt)
    if eff_size <= 0:
        raise ValueError("font size must be greater than zero")
    return eff_size


__all__ = [
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "DEVANAGARI_RE",
    "ENGLISH_FONT",
    "contains_devanagari",
    "normalize_size",
    "output_font",
]
