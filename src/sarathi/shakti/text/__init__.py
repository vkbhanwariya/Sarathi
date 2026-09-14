"""Shared text-processing primitives for Shakti capabilities."""

from __future__ import annotations

from sarathi.shakti.text.direction import NormalizedDirection, normalize_translation_direction
from sarathi.shakti.text.legacy_detection import LegacyFontDetector, is_legacy_text
from sarathi.shakti.text.span_protection import BaseSpanProtector
from sarathi.shakti.text.transliteration import (
    is_romanized_hindi,
    transliterate_romanized_hindi,
    transliterate_word,
)
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
    "NormalizedDirection",
    "contains_devanagari",
    "is_legacy_text",
    "is_romanized_hindi",
    "normalize_size",
    "normalize_translation_direction",
    "output_font",
    "transliterate_romanized_hindi",
    "transliterate_word",
]
