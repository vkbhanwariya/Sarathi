"""Script and Language Identification for Translation."""

from __future__ import annotations

import re

from sarathi.shakti.translation.models import Language, TranslationDirection

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Legacy font signatures (e.g. Kruti Dev markers)
_LEGACY_SIGNATURES = (
    "[k", "vk", "vks", "vkS", "Fk", "/k", "Hk", "'k", ";Z", "jZ", ";k", "D;",
    "x~", "LVs", "cSa", ".k", "fdr", "fd", "fr", "fn", "fc", "f[", "fH", "fF", "fD"
)


class LanguageDetector:
    """Detects source language and verifies normalized Unicode content."""

    def detect_language(self, text: str) -> Language:
        """Identify whether text is primarily Hindi (Devanagari) or English (Latin)."""
        if not text or not text.strip():
            return Language.UNKNOWN

        deva_count = len(_DEVANAGARI_RE.findall(text))
        latin_count = len(_LATIN_RE.findall(text))

        if deva_count > latin_count and deva_count > 0:
            return Language.HINDI
        if latin_count > 0:
            return Language.ENGLISH
        return Language.UNKNOWN

    def is_legacy_font(self, text: str) -> bool:
        """Check if text contains legacy Hindi font markers requiring Roopa Font Conversion."""
        if not text or not text.strip():
            return False
        matches = [s for s in _LEGACY_SIGNATURES if s in text]
        return len(matches) >= 2

    def resolve_direction(
        self,
        text: str,
        requested_direction: str | None = None,
    ) -> TranslationDirection:
        """Resolve translation direction from explicit request or text script density."""
        if requested_direction:
            dir_str = requested_direction.lower().strip()
            if dir_str in ("hi-en", "hindi_to_english", "hi_en"):
                return TranslationDirection.HI_TO_EN
            if dir_str in ("en-hi", "english_to_hindi", "en_hi"):
                return TranslationDirection.EN_TO_HI

        detected = self.detect_language(text)
        if detected == Language.HINDI:
            return TranslationDirection.HI_TO_EN
        return TranslationDirection.EN_TO_HI
