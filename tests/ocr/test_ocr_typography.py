"""Unit tests for OCR capability-local typography helper (sarathi.shakti.ocr.typography)."""

from __future__ import annotations

import sarathi.shakti.ocr.typography as ocr_typo
import sarathi.shakti.text.typography as text_typo
from sarathi.shakti.ocr.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    infer_line_font_size,
)


def test_ocr_typography_exports_match_shared_text_module() -> None:
    """Verify OCR typography module faithfully re-exports shared text primitives."""
    assert ocr_typo.ENGLISH_FONT == text_typo.ENGLISH_FONT == ENGLISH_FONT
    assert ocr_typo.DEVANAGARI_FONT == text_typo.DEVANAGARI_FONT == DEVANAGARI_FONT
    assert ocr_typo.DEFAULT_SIZE_PT == text_typo.DEFAULT_SIZE_PT == DEFAULT_SIZE_PT
    assert ocr_typo.contains_devanagari is text_typo.contains_devanagari
    assert ocr_typo.output_font is text_typo.output_font
    assert ocr_typo.normalize_size is text_typo.normalize_size


def test_infer_line_font_size() -> None:
    """Verify dynamic font size inference and heading detection from bounding box heights."""
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

    # Invalid or zero-height bounding box falls back to default size and non-heading
    size, is_h = infer_line_font_size(None)
    assert size == DEFAULT_SIZE_PT
    assert is_h is False

    size, is_h = infer_line_font_size((10.0, 50.0, 200.0, 50.0))
    assert size == DEFAULT_SIZE_PT
    assert is_h is False

