"""Unit tests for Translation capability-local typography helper."""

import pytest

from sarathi.shakti.text.typography import (
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    contains_devanagari,
    normalize_size,
    output_font,
)


def test_translation_output_font_selection() -> None:
    """Verify font family selection for English, Hindi, and mixed content."""
    # English only
    eng_text = "This petition is allowed."
    assert not contains_devanagari(eng_text)
    assert output_font(contains_devanagari=contains_devanagari(eng_text)) == ENGLISH_FONT
    assert ENGLISH_FONT == "Times New Roman"

    # Hindi only
    hin_text = "यह आवेदन स्वीकार किया गया।"
    assert contains_devanagari(hin_text)
    assert output_font(contains_devanagari=contains_devanagari(hin_text)) == DEVANAGARI_FONT
    assert DEVANAGARI_FONT == "Nirmala UI"

    # Hindi-English mixed
    mixed_text = "Section 482 के अंतर्गत"
    assert contains_devanagari(mixed_text)
    assert output_font(contains_devanagari=contains_devanagari(mixed_text)) == DEVANAGARI_FONT


def test_translation_normalize_size_preserves_logical_size() -> None:
    """Verify logical size is preserved exactly."""
    assert normalize_size(12.0) == 12.0
    assert normalize_size(14.5) == 14.5


def test_translation_normalize_size_invalid() -> None:
    """Verify sizes <= 0 raise ValueError."""
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_size(0)
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_size(-1.0)
