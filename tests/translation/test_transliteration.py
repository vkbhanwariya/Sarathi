"""Tests for Romanized Indic (Hinglish) Detection and Phonetic Transliteration."""

from __future__ import annotations

from sarathi.shakti.text.transliteration import (
    is_romanized_hindi,
    transliterate_romanized_hindi,
    transliterate_word,
)
from sarathi.shakti.translation.detector import LanguageDetector


def test_transliterate_canonical_administrative_words() -> None:
    assert transliterate_word("kripya") == "कृपया"
    assert transliterate_word("dhanyawad") == "धन्यवाद"
    assert transliterate_word("dhanyavad") == "धन्यवाद"
    assert transliterate_word("namaste") == "नमस्ते"
    assert transliterate_word("sarkar") == "सरकार"
    assert transliterate_word("bharat") == "भारत"
    assert transliterate_word("aavedan") == "आवेदन"
    assert transliterate_word("suchana") == "सूचना"
    assert transliterate_word("aadesh") == "आदेश"


def test_transliterate_full_romanized_sentence() -> None:
    text = "Kripya aavedan patra pradan karein."
    expected = "कृपया आवेदन पत्र प्रदान करें."
    assert transliterate_romanized_hindi(text) == expected


def test_is_romanized_hindi_detection() -> None:
    # Multiple diagnostic administrative terms
    assert is_romanized_hindi("Kripya aavedan patra pradan karein.") is True
    assert is_romanized_hindi("sarkar dwara suchana") is True
    assert is_romanized_hindi("namaste") is True

    # Standard English must NOT be detected as Romanized Hindi
    assert is_romanized_hindi("Official Government of India Order.") is False
    assert is_romanized_hindi("Please submit the application form.") is False
    assert is_romanized_hindi("") is False


def test_language_detector_transliteration_integration() -> None:
    detector = LanguageDetector()
    sample = "Kripya aavedan karein."

    assert detector.is_romanized_hindi(sample) is True
    assert detector.transliterate(sample) == "कृपया आवेदन करें."
    assert detector.is_romanized_hindi("Annual Financial Statement Report") is False
