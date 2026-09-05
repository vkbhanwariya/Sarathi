"""Shared text processing and protection utilities for Shakti capabilities."""

from __future__ import annotations

from sarathi.shakti.text.legacy_detection import (
    _CHANAKYA_SIGNATURES,
    _KNOWN_MODERN_FONTS,
    _KRUTI_SIGNATURES,
    _SHUSHA_SIGNATURES,
    LegacyFontDetector,
    is_legacy_text,
)
from sarathi.shakti.text.span_protection import (
    _DATE_RE,
    _EMAIL_RE,
    _ID_RE,
    _NUM_RE,
    _PERCENT_RE,
    _PROT_END,
    _PROT_START,
    _UNICODE_DEVANAGARI_RE,
    _URL_RE,
    BaseSpanProtector,
)

__all__ = [
    "BaseSpanProtector",
    "LegacyFontDetector",
    "is_legacy_text",
    "_PROT_START",
    "_PROT_END",
    "_URL_RE",
    "_EMAIL_RE",
    "_UNICODE_DEVANAGARI_RE",
    "_DATE_RE",
    "_NUM_RE",
    "_PERCENT_RE",
    "_ID_RE",
    "_KRUTI_SIGNATURES",
    "_CHANAKYA_SIGNATURES",
    "_SHUSHA_SIGNATURES",
    "_KNOWN_MODERN_FONTS",
]
