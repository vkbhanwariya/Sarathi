"""Tests for Language Detection and Legacy Font Handoff."""

from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.models import Language, TranslationDirection


def test_language_script_detection() -> None:
    detector = LanguageDetector()

    assert detector.detect_language("भारत सरकार का आधिकारिक आदेश।") == Language.HINDI
    assert detector.detect_language("Official Government of India Order.") == Language.ENGLISH
    assert detector.detect_language("") == Language.UNKNOWN


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
