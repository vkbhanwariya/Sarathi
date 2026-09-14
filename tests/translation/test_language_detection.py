"""Tests for Language Detection and Legacy Font Handoff."""

import pytest

from sarathi.dosh import DoshError
from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.models import Language, TranslationDirection


def test_language_script_detection() -> None:
    detector = LanguageDetector()

    assert detector.detect_language("भारत सरकार का आधिकारिक आदेश।") == Language.HINDI
    assert detector.detect_language("Official Government of India Order.") == Language.ENGLISH
    assert detector.detect_language("") == Language.UNKNOWN
    # Marathi with distinct character 'ळ'
    assert detector.detect_language("शाळा आणि महाविद्यालय") == Language.MARATHI
    # Marathi with lexical markers
    assert detector.detect_language("महाराष्ट्र शासनाचा अधिकृत निर्णय आहे.") == Language.MARATHI
    # Nepali with lexical markers
    assert detector.detect_language("नेपाल सरकारको यो निर्णय भएको छ.") == Language.NEPALI
    # Sanskrit with lexical markers
    assert detector.detect_language("सत्यमेव जयते नानृतम्। ईश्वरः अस्ति।") == Language.SANSKRIT


def test_devanagari_non_hindi_resolution_guards() -> None:
    detector = LanguageDetector()

    # Marathi without explicit direction raises DoshError to prevent corrupt translation
    with pytest.raises(DoshError) as exc:
        detector.resolve_direction("महाराष्ट्र शासनाचा अधिकृत निर्णय आहे.")
    assert "Detected source language is Marathi (mr)" in exc.value.message

    # Explicit direction overrides guard
    assert (
        detector.resolve_direction(
            "महाराष्ट्र शासनाचा अधिकृत निर्णय आहे.",
            requested_direction="hi-en",
        )
        == TranslationDirection.HI_TO_EN
    )


def test_direction_resolution() -> None:
    detector = LanguageDetector()

    assert detector.resolve_direction("भारत सरकार") == TranslationDirection.HI_TO_EN
    assert detector.resolve_direction("Government of India") == TranslationDirection.EN_TO_HI
    assert detector.resolve_direction("Random text", requested_direction="en-hi") == TranslationDirection.EN_TO_HI


def test_legacy_font_detection_triggers_handoff() -> None:
    detector = LanguageDetector()

    # Kruti dev signature digraphs
    legacy_sample = "LVsV cSad vksj Hkkjr ljdkj"
    assert detector.is_legacy_font(legacy_sample) is True

    # Standard English and Unicode Hindi are NOT legacy font
    assert detector.is_legacy_font("Standard English Document") is False
    assert detector.is_legacy_font("मानक हिंदी दस्तावेज़") is False


def test_translation_unknown_language_raises_dosh_error() -> None:
    """Verify LanguageDetector rejects unknown language and unsupported directions."""
    detector = LanguageDetector()

    # Unknown language text without explicit direction must raise DoshError
    with pytest.raises(DoshError) as exc_info:
        detector.resolve_direction("12345 !@#$%")
    assert "Unable to detect language from input text" in exc_info.value.message

    # Invalid requested direction must raise DoshError
    with pytest.raises(DoshError) as exc_info2:
        detector.resolve_direction("Hello world", requested_direction="es-fr")
    assert "Unsupported or invalid translation direction" in exc_info2.value.message


def test_normalize_translation_direction() -> None:
    from sarathi.shakti.text import normalize_translation_direction

    # Common UI formats
    d1 = normalize_translation_direction("en_hi")
    assert d1.source_code == "en" and d1.target_code == "hi"
    assert d1.source_name == "English" and d1.target_name == "Hindi"

    d2 = normalize_translation_direction("hi_en")
    assert d2.source_code == "hi" and d2.target_code == "en"
    assert d2.source_name == "Hindi" and d2.target_name == "English"

    # Hyphenated and arrow formats
    assert normalize_translation_direction("en-hi").target_code == "hi"
    assert normalize_translation_direction("hi->en").target_code == "en"
    assert normalize_translation_direction("en_to_hi").target_code == "hi"

    # Auto directions
    assert normalize_translation_direction("auto-en").source_code == "auto"
    assert normalize_translation_direction("auto_hi").source_code == "auto"

    # Default fallback on None or empty
    assert normalize_translation_direction(None).source_code == "hi"
    assert normalize_translation_direction("").target_code == "en"
