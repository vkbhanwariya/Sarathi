"""Unit tests for shared Shakti text typography helpers (sarathi.shakti.text.typography)."""

from __future__ import annotations

import pytest

from sarathi.shakti.text.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    classify_page_lines,
    contains_devanagari,
    detect_running_headers_footers,
    heal_devanagari_matra_spacing,
    normalize_header_template,
    normalize_size,
    normalize_text_spacing,
    output_font,
    reconstruct_line_from_spans,
)


def test_output_font_selection() -> None:
    """Verify font family selection for English, Hindi, and mixed content."""
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


def test_normalize_size_reliable_and_default() -> None:
    """Verify valid sizes are preserved and None falls back to DEFAULT_SIZE_PT."""
    assert normalize_size(14.0) == 14.0
    assert normalize_size(12.5) == 12.5
    assert normalize_size(None) == DEFAULT_SIZE_PT
    assert DEFAULT_SIZE_PT == 12.0


def test_normalize_size_invalid() -> None:
    """Verify sizes <= 0 raise ValueError."""
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_size(0)
    with pytest.raises(ValueError, match="greater than zero"):
        normalize_size(-5.0)


def test_heal_devanagari_matra_spacing() -> None:
    """Verify inadvertent spaces before vowel matras and halant gaps are repaired."""
    # Matra with space
    assert heal_devanagari_matra_spacing("क ि") == "कि"
    assert heal_devanagari_matra_spacing("प ्रा") == "प्रा"


def test_normalize_text_spacing() -> None:
    """Verify text spacing and punctuation normalization."""
    raw = "Section 482  ,  CrPC  ( 2024 ) .  "
    assert normalize_text_spacing(raw) == "Section 482, CrPC (2024)."


def test_reconstruct_line_from_spans() -> None:
    """Verify spatial line reconstruction from bounding-box gaps."""
    spans = [
        ("High", (10.0, 10.0, 40.0, 25.0), 12.0),
        ("Court", (45.0, 10.0, 85.0, 25.0), 12.0),
    ]
    assert reconstruct_line_from_spans(spans) == "High Court"


def test_running_header_footer_detection_and_clean_separation() -> None:
    """Verify cross-page recurring header/footer pattern detection and line classification."""
    # 1. Template normalization
    assert normalize_header_template("[2026:RJ-JP:18881][CRLMP-4154/2023](2 of 39)") == "[#:rj-jp:#][crlmp-#/#](# of #)"
    assert normalize_header_template("[2026:RJ-JP:18881][CRLMP-4154/2023](3 of 39)") == "[#:rj-jp:#][crlmp-#/#](# of #)"
    assert normalize_header_template("विविध प्रार्थना पत्र संख्या ः 04@2023") == "विविध प्रार्थना पत्र संख्या ः #@#"

    # 2. 3-page document with pixel coordinates
    page_1 = [
        ("[2026:RJ-JP:18881][CRLMP-4154/2023](1 of 3)", (50.0, 40.0, 400.0, 70.0)),
        ("HIGH COURT OF JUDICATURE FOR RAJASTHAN", (50.0, 180.0, 500.0, 210.0)),
        ("First paragraph of legal reasoning.", (50.0, 230.0, 450.0, 260.0)),
        ("Page 1 Footer Notice", (50.0, 1120.0, 300.0, 1150.0)),
    ]
    page_2 = [
        ("[2026:RJ-JP:18881][CRLMP-4154/2023](2 of 3)", (50.0, 42.0, 400.0, 72.0)),
        ("Second paragraph continuing argument.", (50.0, 180.0, 480.0, 210.0)),
        ("Page 2 Footer Notice", (50.0, 1122.0, 300.0, 1152.0)),
    ]
    page_3 = [
        ("[2026:RJ-JP:18881][CRLMP-4154/2023](3 of 3)", (50.0, 39.0, 400.0, 69.0)),
        ("Final order operative directions.", (50.0, 180.0, 460.0, 210.0)),
        ("Page 3 Footer Notice", (50.0, 1118.0, 300.0, 1148.0)),
    ]

    all_pages = [page_1, page_2, page_3]
    page_heights = [1200.0, 1200.0, 1200.0]

    header_tmpls, footer_tmpls = detect_running_headers_footers(all_pages, page_heights)
    assert "[#:rj-jp:#][crlmp-#/#](# of #)" in header_tmpls
    assert "page # footer notice" in footer_tmpls

    # Classify page 2
    body, headers, footers = classify_page_lines(page_2, 1200.0, header_tmpls, footer_tmpls)
    assert body == ["Second paragraph continuing argument."]
    assert headers == ["[2026:RJ-JP:18881][CRLMP-4154/2023](2 of 3)"]
    assert footers == ["Page 2 Footer Notice"]
