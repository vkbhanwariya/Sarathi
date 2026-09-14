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


def test_ocr_running_header_footer_detection_and_clean_separation() -> None:
    """Verify that OCR text spans with recurring headers are detected and cleanly separated."""
    from sarathi.shakti.text.typography import (
        classify_page_lines,
        detect_running_headers_footers,
        normalize_header_template,
    )

    # Test template normalizer with OCR noise and variable numerals
    assert normalize_header_template("[2026:RJ-JP:18881][CRLMP-4154/2023](2 of 39)") == "[#:rj-jp:#][crlmp-#/#](# of #)"
    assert normalize_header_template("[2026:RJ-JP:18881][CRLMP-4154/2023](3 of 39)") == "[#:rj-jp:#][crlmp-#/#](# of #)"
    assert normalize_header_template("विविध प्रार्थना पत्र संख्या ः 04@2023") == "विविध प्रार्थना पत्र संख्या ः #@#"

    # 3-page OCR document with pixel coordinates (height=1200)
    page_1_items = [
        ("[2026:RJ-JP:18881][CRLMP-4154/2023](1 of 3)", (50.0, 40.0, 400.0, 70.0)),
        ("HIGH COURT OF JUDICATURE FOR RAJASTHAN", (50.0, 180.0, 500.0, 210.0)),
        ("First paragraph of legal reasoning.", (50.0, 230.0, 450.0, 260.0)),
        ("Page 1 Footer Notice", (50.0, 1120.0, 300.0, 1150.0)),
    ]
    page_2_items = [
        ("[2026:RJ-JP:18881][CRLMP-4154/2023](2 of 3)", (50.0, 42.0, 400.0, 72.0)),
        ("Second paragraph continuing argument.", (50.0, 180.0, 480.0, 210.0)),
        ("Page 2 Footer Notice", (50.0, 1122.0, 300.0, 1152.0)),
    ]
    page_3_items = [
        ("[2026:RJ-JP:18881][CRLMP-4154/2023](3 of 3)", (50.0, 39.0, 400.0, 69.0)),
        ("Final order operative directions.", (50.0, 180.0, 460.0, 210.0)),
        ("Page 3 Footer Notice", (50.0, 1118.0, 300.0, 1148.0)),
    ]

    all_pages = [page_1_items, page_2_items, page_3_items]
    page_heights = [1200.0, 1200.0, 1200.0]

    header_tmpls, footer_tmpls = detect_running_headers_footers(all_pages, page_heights)
    assert "[#:rj-jp:#][crlmp-#/#](# of #)" in header_tmpls
    assert "page # footer notice" in footer_tmpls

    # Classify page 2
    body, headers, footers = classify_page_lines(page_2_items, 1200.0, header_tmpls, footer_tmpls)
    assert body == ["Second paragraph continuing argument."]
    assert headers == ["[2026:RJ-JP:18881][CRLMP-4154/2023](2 of 3)"]
    assert footers == ["Page 2 Footer Notice"]

