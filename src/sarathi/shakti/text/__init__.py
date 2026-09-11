"""Shared text-processing primitives for Shakti capabilities."""

from __future__ import annotations

from sarathi.shakti.text.legacy_detection import LegacyFontDetector, is_legacy_text
from sarathi.shakti.text.span_protection import BaseSpanProtector
from sarathi.shakti.text.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    DEVANAGARI_RE,
    ENGLISH_FONT,
    contains_devanagari,
    normalize_size,
    output_font,
)

__all__ = [
    "BaseSpanProtector",
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "DEVANAGARI_RE",
    "ENGLISH_FONT",
    "LegacyFontDetector",
    "contains_devanagari",
    "is_legacy_text",
    "normalize_size",
    "output_font",
]
