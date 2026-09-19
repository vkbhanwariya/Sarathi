"""Unit Tests for Proper-Noun Legal Transliteration Guard (Phase 5)."""

from __future__ import annotations

from sarathi.shakti.translation.proper_noun_guard import (
    ProperNounGuard,
    transliterate_devanagari_to_latin,
)


def test_devanagari_phonetic_transliteration() -> None:
    """Verify ISO/phonetic transliteration of common Indian names and places."""
    assert transliterate_devanagari_to_latin("रामप्रसाद") == "Ramprasad"
    assert transliterate_devanagari_to_latin("सूर्यभान") == "Suryabhan"
    assert transliterate_devanagari_to_latin("सुखदेव") == "Sukhadev"
    assert transliterate_devanagari_to_latin("विजय कुमार") == "Vijay Kumar"
    assert transliterate_devanagari_to_latin("रामपुर") == "Rampur"


def test_proper_noun_protection_and_restoration_lifecycle() -> None:
    """Verify honorific, kinship, and village prefixes are protected and restored in English."""
    guard = ProperNounGuard()

    hindi_source = "अभियुक्त श्री रामप्रसाद पुत्र सुखदेव निवासी ग्राम रामपुर तहसील बयाना जिला भरतपुर।"

    protected_text, placeholders = guard.protect(hindi_source)
    assert len(placeholders) >= 3
    # Verify placeholders are embedded in text
    assert "__NAME_1__" in protected_text
    assert "__NAME_2__" in protected_text
    assert "__NAME_3__" in protected_text

    # Verify placeholder values are transliterated names
    trans_map = dict(placeholders)
    assert trans_map["__NAME_1__"] == "Ramprasad"
    assert trans_map["__NAME_2__"] == "Sukhadev"
    assert trans_map["__NAME_3__"] == "Rampur"

    # Simulate NMT translation translating surrounding text to English while preserving placeholders
    simulated_nmt_output = (
        "The accused Mr. __NAME_1__ s/o __NAME_2__ resident of village __NAME_3__ tehsil Bayana district Bharatpur."
    )

    restored_text = guard.restore(simulated_nmt_output, placeholders)
    assert "Mr. Ramprasad" in restored_text
    assert "s/o Sukhadev" in restored_text
    assert "village Rampur" in restored_text

    # Invariant: Semantic hallucination (e.g. 'Happy God' for सुखदेव) must never appear
    assert "Happy God" not in restored_text
    assert "Sun Light" not in restored_text
