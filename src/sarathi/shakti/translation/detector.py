"""Script and Language Identification for Translation."""

from __future__ import annotations

import re

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.text.legacy_detection import LegacyFontDetector
from sarathi.shakti.text.transliteration import is_romanized_hindi, transliterate_romanized_hindi
from sarathi.shakti.text.typography import DEVANAGARI_RE as _DEVANAGARI_RE
from sarathi.shakti.translation.models import Language, TranslationDirection

_LATIN_RE = re.compile(r"[A-Za-z]")
_MARATHI_SPECIFIC_CHAR_RE = re.compile(r"[\u0933\u0934]")  # ळ, ऴ
_WORD_TOKEN_RE = re.compile(r"[\u0900-\u0963\u0970-\u097f]+")

_MARATHI_MARKERS = frozenset({
    "आहे", "आहेत", "नाही", "झाले", "झाली", "झाला", "करणे", "म्हणून",
    "केले", "केली", "केला", "त्यांच्या", "दिवशी", "कामासाठी", "शासन", "महाराष्ट्र",
})
_NEPALI_MARKERS = frozenset({
    "छ", "छन्", "भयो", "गरेको", "गरेका", "हुन", "लागि", "भने",
    "थियो", "गर्नु", "नेपाल", "सरकारको", "भएको",
})
_SANSKRIT_MARKERS = frozenset({
    "अस्ति", "इति", "भवति", "तथा", "अपि", "एव", "यथा", "सर्वम्", "नमः", "उवाच",
})
_HINDI_MARKERS = frozenset({
    "है", "हैं", "था", "थी", "थे", "किया", "होगा", "होगी", "लिए",
    "और", "का", "के", "की", "यह", "वह", "सरकार", "भारत",
})


def _discriminate_devanagari_language(text: str) -> Language:
    """Discriminate Devanagari sub-languages using diagnostic characters and lexical markers."""
    if _MARATHI_SPECIFIC_CHAR_RE.search(text):
        return Language.MARATHI

    tokens = set(_WORD_TOKEN_RE.findall(text))
    if not tokens:
        return Language.HINDI

    marathi_score = len(tokens & _MARATHI_MARKERS)
    nepali_score = len(tokens & _NEPALI_MARKERS)
    sanskrit_score = len(tokens & _SANSKRIT_MARKERS)
    hindi_score = len(tokens & _HINDI_MARKERS)

    if marathi_score > 0 and marathi_score > hindi_score:
        return Language.MARATHI
    if nepali_score > 0 and nepali_score > hindi_score:
        return Language.NEPALI
    if sanskrit_score > 0 and sanskrit_score > hindi_score:
        return Language.SANSKRIT

    return Language.HINDI


class LanguageDetector:
    """Detects source language and verifies normalized Unicode content."""

    def detect_language(self, text: str) -> Language:
        """Identify whether text is Hindi, Marathi, Nepali, Sanskrit (Devanagari) or English (Latin)."""
        if not text or not text.strip():
            return Language.UNKNOWN

        deva_count = len(_DEVANAGARI_RE.findall(text))
        latin_count = len(_LATIN_RE.findall(text))

        if deva_count > latin_count and deva_count > 0:
            return _discriminate_devanagari_language(text)
        if latin_count > 0:
            return Language.ENGLISH
        return Language.UNKNOWN

    def is_legacy_font(self, text: str) -> bool:
        """Check if text contains legacy Hindi font markers requiring Roopa Font Conversion."""
        return LegacyFontDetector.is_legacy_text(text)

    def is_romanized_hindi(self, text: str) -> bool:
        """Check if Latin text contains Romanized Hindi (Hinglish) requiring transliteration."""
        return is_romanized_hindi(text)

    def transliterate(self, text: str) -> str:
        """Transliterate Romanized Hindi into standardized Unicode Devanagari."""
        return transliterate_romanized_hindi(text)

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
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Unsupported or invalid translation direction: {requested_direction!r}",
            )

        detected = self.detect_language(text)
        if detected == Language.HINDI:
            return TranslationDirection.HI_TO_EN
        if detected == Language.ENGLISH:
            return TranslationDirection.EN_TO_HI
        if detected in (Language.MARATHI, Language.NEPALI, Language.SANSKRIT):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=(
                    f"Detected source language is {detected.name.capitalize()} ({detected.value}), "
                    "which is not supported by the default Hindi-English translation model. "
                    "Specify an explicit translation direction if you wish to override."
                ),
            )

        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Unable to detect language from input text; unknown language cannot be resolved.",
        )
