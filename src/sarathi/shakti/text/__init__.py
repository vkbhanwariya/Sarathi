"""Shared text-processing primitives for Shakti capabilities."""

from __future__ import annotations

from sarathi.shakti.text.direction import NormalizedDirection, normalize_translation_direction
from sarathi.shakti.text.lazy import lazy_exports
from sarathi.shakti.text.legacy_detection import LegacyFontDetector, is_legacy_text
from sarathi.shakti.text.legacy_fonts import (
    LegacyFontProfile,
    load_font_profiles,
    resolve_profile_from_font_name,
)
from sarathi.shakti.text.safe_zip import SafeZipFile, open_zip_safely, safe_fromstring
from sarathi.shakti.text.span_protection import BaseSpanProtector
from sarathi.shakti.text.table import cell_text
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
    normalize_devanagari_numerals,
    normalize_size,
    output_font,
)
from sarathi.shakti.text.usability import is_usable_document, is_usable_page

__all__ = [
    "BaseSpanProtector",
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "DEVANAGARI_RE",
    "ENGLISH_FONT",
    "LegacyFontDetector",
    "LegacyFontProfile",
    "NormalizedDirection",
    "SafeZipFile",
    "cell_text",
    "contains_devanagari",
    "is_legacy_text",
    "is_romanized_hindi",
    "is_usable_document",
    "is_usable_page",
    "lazy_exports",
    "load_font_profiles",
    "normalize_devanagari_numerals",
    "normalize_size",
    "normalize_translation_direction",
    "open_zip_safely",
    "output_font",
    "resolve_profile_from_font_name",
    "safe_fromstring",
    "transliterate_romanized_hindi",
    "transliterate_word",
]
