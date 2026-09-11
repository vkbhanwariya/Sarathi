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
