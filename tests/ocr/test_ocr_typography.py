"""Unit tests for OCR capability-local typography helper."""

import pytest

from sarathi.shakti.ocr.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    contains_devanagari,
    normalize_size,
    output_font,
)


def test_ocr_output_font_selection() -> None:
    """Verify font family selection for English, Hindi, and mixed OCR text."""
    # English only
    eng_text = "AFFIDAVIT IN SUPPORT OF PETITION"
    assert not contains_devanagari(eng_text)
    assert output_font(contains_devanagari=contains_devanagari(eng_text)) == ENGLISH_FONT
    assert ENGLISH_FONT == "Times New Roman"

    # Hindi only
    hin_text = "शपथ पत्र प्रारूप"
    assert contains_devanagari(hin_text)
    assert output_font(contains_devanagari=contains_devanagari(hin_text)) == DEVANAGARI_FONT
    assert DEVANAGARI_FONT == "Nirmala UI"

    # Mixed
    mixed_text = "Section 482 CrPC के तहत प्रस्तुत"
    assert contains_devanagari(mixed_text)
    assert output_font(contains_devanagari=contains_devanagari(mixed_text)) == DEVANAGARI_FONT


def test_ocr_normalize_size_reliable_and_default() -> None:
    """Verify reliable size is preserved and None falls back to default 12 pt."""
    assert normalize_size(14.0) == 14.0
    assert normalize_size(None) == DEFAULT_SIZE_PT
    assert DEFAULT_SIZE_PT == 12.0


def test_ocr_normalize_size_invalid() -> None:
    """Verify sizes <= 0 raise ValueError."""
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_size(0)
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_size(-5.0)


def test_infer_line_font_size() -> None:
    """Verify dynamic font size inference and heading detection from bounding box heights."""
    from sarathi.shakti.ocr.typography import infer_line_font_size

    # Title line with 2.0x median line height
    size, is_h = infer_line_font_size((10.0, 50.0, 200.0, 110.0), median_line_height=30.0)
    assert size == 18.0
    assert is_h is True

    # Section heading with 1.4x median line height
    size, is_h = infer_line_font_size((10.0, 50.0, 200.0, 92.0), median_line_height=30.0)
    assert size == 15.0
    assert is_h is True

    # Standard body line (1.0x median line height)
    size, is_h = infer_line_font_size((10.0, 50.0, 200.0, 80.0), median_line_height=30.0)
    assert size == 12.0
    assert is_h is False

    # Small footnote (0.7x median line height)
    size, is_h = infer_line_font_size((10.0, 50.0, 200.0, 71.0), median_line_height=30.0)
    assert size == 10.0
    assert is_h is False

