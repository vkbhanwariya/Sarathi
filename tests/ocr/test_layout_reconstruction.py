"""Focused regression tests for OCR paragraph reconstruction and semantic layout/table detection.

Validates:
1. Continuous paragraph reconstruction across all OCR execution modes (INSTANT, ACCURATE, LAYOUT_PRESERVING, CUSTOM).
2. Genuine paragraph breaks (large vertical gap, indentation, early line termination).
3. Headings and list bullet items preserved as distinct blocks.
4. Multi-column reading order via Recursive XY-Cut (no horizontal column interweaving).
5. Ruled table detection via OpenCV morphology and TableData synthesis.
6. Borderless table detection via coordinate-based row/column alignment.
7. Layout reconstruction gating: tables produced ONLY in LAYOUT_PRESERVING and CUSTOM(preserve_layout=True).
8. Layout-preserving DOCX export: Word <w:tbl> generated from PageData.tables.
9. Zero alteration of original OCR span text evidence and confidence scores.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image, ImageDraw

from sarathi.sankalpa import (
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
    TextSpan,
)
from sarathi.shakti.ocr import OCRCapability
from sarathi.shakti.ocr.capability import _is_usable_page
from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine
from sarathi.shakti.ocr.engine.layout import (
    detect_borderless_tables,
    detect_column_count,
    detect_ruled_tables,
    group_paragraphs,
    reconstruct_layout,
)


def _make_span(text: str, bbox: tuple[float, float, float, float], conf: float = 0.95) -> TextSpan:
    return TextSpan(
        text=text,
        bounding_box=bbox,
        confidence=conf,
        language="en",
        script="Latn",
    )


# ==============================================================================
# 1. Continuous Paragraph Reconstruction in all OCR modes
# ==============================================================================

@pytest.mark.parametrize(
    "profile,custom_opts",
    [
        (ExecutionProfile.INSTANT, {}),
        (ExecutionProfile.ACCURATE, {}),
        (ExecutionProfile.LAYOUT_PRESERVING, {}),
        (ExecutionProfile.CUSTOM, {"engine": "rapidocr"}),
        (ExecutionProfile.CUSTOM, {"engine": "rapidocr", "preserve_layout": True}),
        (ExecutionProfile.CUSTOM, {"engine": "rapidocr", "preserve_layout": False}),
    ],
)
def test_continuous_paragraph_reconstruction_in_all_modes(
    profile: ExecutionProfile,
    custom_opts: dict[str, Any],
) -> None:
    """Proves lines belonging to the same paragraph are joined with spaces across all OCR profiles."""
    engine = RapidOCREngine()

    # Three wrapped lines belonging to the same paragraph
    spans = [
        _make_span("This is the first sentence of a", (50.0, 50.0, 350.0, 70.0)),
        _make_span("continuous paragraph that wraps across", (50.0, 75.0, 360.0, 95.0)),
        _make_span("multiple detected visual rows cleanly.", (50.0, 100.0, 340.0, 120.0)),
    ]

    # Mock engine inference to return these 3 lines
    mock_output = MagicMock()
    mock_output.txts = [s.text for s in spans]
    mock_output.boxes = [
        [[s.bounding_box[0], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[3]],
         [s.bounding_box[0], s.bounding_box[3]]]
        for s in spans
    ]
    mock_output.scores = [0.95, 0.94, 0.96]
    engine._engine = lambda arr, **kw: mock_output

    test_img = Image.new("RGB", (500, 200), color="white")
    page_data, _, _, _ = engine.ocr_page(
        test_img,
        page_number=1,
        input_id="test_para",
        profile=profile,
        custom_options=custom_opts,
    )

    expected = "This is the first sentence of a continuous paragraph that wraps across multiple detected visual rows cleanly."
    assert page_data.text.strip() == expected
    assert "\n" not in page_data.text.strip(), "Consecutive rows in same paragraph must be joined with space, not newline"


# ==============================================================================
# 2. Genuine Paragraph Breaks (Gap, Indent, Early Terminal Line)
# ==============================================================================

def test_genuine_paragraph_breaks_preserved() -> None:
    """Proves large vertical gap, first-line indent, and early terminal line create real breaks."""
    spans = [
        # Paragraph 1
        _make_span("First paragraph line one.", (50.0, 50.0, 350.0, 70.0)),
        _make_span("First paragraph line two concludes here.", (50.0, 75.0, 200.0, 95.0)),  # early terminal line
        # Paragraph 2 (separated by large gap)
        _make_span("Second paragraph line one.", (50.0, 150.0, 350.0, 170.0)),
        _make_span("Second paragraph line two.", (50.0, 175.0, 350.0, 195.0)),
        # Paragraph 3 (starts with indent)
        _make_span("Third paragraph indented start.", (85.0, 220.0, 350.0, 240.0)),
        _make_span("Third paragraph continued line.", (50.0, 245.0, 350.0, 265.0)),
    ]

    text = group_paragraphs(spans)
    paragraphs = text.split("\n\n")

    assert len(paragraphs) == 3, f"Expected 3 distinct paragraphs, got {len(paragraphs)}: {paragraphs}"
    assert paragraphs[0] == "First paragraph line one. First paragraph line two concludes here."
    assert paragraphs[1] == "Second paragraph line one. Second paragraph line two."
    assert paragraphs[2] == "Third paragraph indented start. Third paragraph continued line."


# ==============================================================================
# 3. Headings and List Bullet Items
# ==============================================================================

def test_headings_and_lists_preserved() -> None:
    """Proves headings and bullet/numbered list items are kept distinct from normal paragraphs."""
    spans = [
        # Large heading (line height 30px vs median 18px)
        _make_span("ANNUAL FINANCIAL REPORT", (50.0, 30.0, 400.0, 65.0)),
        # Body paragraph
        _make_span("The following report outlines financial performance", (50.0, 85.0, 420.0, 105.0)),
        _make_span("for the fiscal year ended March 31, 2026.", (50.0, 110.0, 380.0, 130.0)),
        # List item 1
        _make_span("1. Total revenue increased by fifteen percent.", (50.0, 150.0, 420.0, 170.0)),
        # List item 2
        _make_span("2. Operating expenses remained under budget.", (50.0, 180.0, 410.0, 200.0)),
        # Bullet item
        _make_span("• Net profit reached record highs.", (50.0, 210.0, 350.0, 230.0)),
    ]

    text = group_paragraphs(spans)
    blocks = text.split("\n\n")

    assert blocks[0] == "# ANNUAL FINANCIAL REPORT"
    assert "The following report outlines" in blocks[1]
    assert "1. Total revenue increased" in text
    assert "2. Operating expenses remained" in text
    assert "• Net profit reached" in text
    # List items must not be merged into the body paragraph
    assert "March 31, 2026. 1. Total revenue" not in text


def test_font_metric_gap_aware_span_reconstruction_in_lines() -> None:
    """Proves adjacent spans with sub-character gaps do not get spurious spaces."""
    spans = [
        _make_span("Sar", (50.0, 50.0, 70.0, 70.0)),
        _make_span("athi", (71.0, 50.0, 100.0, 70.0)),  # 1px gap < 0.20 * 20 -> no space inserted
        _make_span("Document", (120.0, 50.0, 180.0, 70.0)),  # 20px gap >= 0.20 * 20 -> space inserted
    ]
    text = group_paragraphs(spans)
    assert "Sarathi Document" in text
    assert "Sar athi" not in text


# ==============================================================================
# 4. Multi-Column Reading Order
# ==============================================================================

def test_multi_column_reading_order_preservation() -> None:
    """Proves Recursive XY-Cut reads left column completely before right column."""
    spans = [
        # Left column (x in [50, 200])
        _make_span("Left column line 1.", (50.0, 50.0, 200.0, 70.0)),
        _make_span("Left column line 2.", (50.0, 75.0, 200.0, 95.0)),
        _make_span("Left column line 3.", (50.0, 100.0, 200.0, 120.0)),
        # Right column (x in [300, 450])
        _make_span("Right column line 1.", (300.0, 50.0, 450.0, 70.0)),
        _make_span("Right column line 2.", (300.0, 75.0, 450.0, 95.0)),
        _make_span("Right column line 3.", (300.0, 100.0, 450.0, 120.0)),
    ]

    text, _ = reconstruct_layout(None, spans, preserve_layout=False)

    # All left column lines must appear before right column lines
    pos_left_3 = text.find("Left column line 3.")
    pos_right_1 = text.find("Right column line 1.")
    assert pos_left_3 != -1 and pos_right_1 != -1
    assert pos_left_3 < pos_right_1, "Left column must be read in full before right column begins"


# ==============================================================================
# 5. Ruled Table Detection
# ==============================================================================

def test_ruled_table_detection() -> None:
    """Proves OpenCV morphological line detection finds ruled tables and extracts TableData."""
    # Create image with a 3x3 table grid
    w, h = 600, 300
    img = Image.new("RGB", (w, h), color="white")
    draw = ImageDraw.Draw(img)

    # Outer table border
    draw.rectangle([50, 50, 550, 250], outline="black", width=2)
    # Horizontal divider lines
    draw.line([50, 110, 550, 110], fill="black", width=2)
    draw.line([50, 180, 550, 180], fill="black", width=2)
    # Vertical divider lines
    draw.line([200, 50, 200, 250], fill="black", width=2)
    draw.line([380, 50, 380, 250], fill="black", width=2)

    img_arr = np.array(img)

    # Spans inside the cells
    spans = [
        # Headers (y in [50, 110])
        _make_span("Invoice No", (60.0, 70.0, 180.0, 90.0)),
        _make_span("Customer", (210.0, 70.0, 350.0, 90.0)),
        _make_span("Amount", (390.0, 70.0, 520.0, 90.0)),
        # Row 1 (y in [110, 180])
        _make_span("INV-001", (60.0, 130.0, 150.0, 150.0)),
        _make_span("Acme Corp", (210.0, 130.0, 300.0, 150.0)),
        _make_span("12,500", (390.0, 130.0, 480.0, 150.0)),
        # Row 2 (y in [180, 250])
        _make_span("INV-002", (60.0, 200.0, 150.0, 220.0)),
        _make_span("Beta Ltd", (210.0, 200.0, 300.0, 220.0)),
        _make_span("45,000", (390.0, 200.0, 480.0, 220.0)),
    ]

    tables, consumed = detect_ruled_tables(img_arr, spans)

    assert len(tables) == 1
    table = tables[0]
    assert table.metadata.get("kind") == "ruled_table"
    assert len(table.headers) == 3
    assert "Invoice No" in table.headers[0]
    assert "Customer" in table.headers[1]
    assert "Amount" in table.headers[2]
    assert len(table.rows) == 2
    assert "INV-001" in table.rows[0][0]
    assert "Beta Ltd" in table.rows[1][1]
    assert len(consumed) == len(spans)


# ==============================================================================
# 6. Borderless Table Detection
# ==============================================================================

def test_borderless_table_detection() -> None:
    """Proves coordinate-based column alignment extracts borderless tables without lines."""
    spans = [
        # Row 0: Headers
        _make_span("Item Description", (50.0, 100.0, 180.0, 120.0)),
        _make_span("Qty", (250.0, 100.0, 290.0, 120.0)),
        _make_span("Rate", (380.0, 100.0, 430.0, 120.0)),
        _make_span("Total", (500.0, 100.0, 550.0, 120.0)),
        # Row 1: Data 1
        _make_span("Steel Rods 10mm", (50.0, 130.0, 190.0, 150.0)),
        _make_span("50", (250.0, 130.0, 270.0, 150.0)),
        _make_span("450.00", (380.0, 130.0, 440.0, 150.0)),
        _make_span("22,500", (500.0, 130.0, 560.0, 150.0)),
        # Row 2: Data 2
        _make_span("Cement Bags OPC", (50.0, 160.0, 195.0, 180.0)),
        _make_span("100", (250.0, 160.0, 280.0, 180.0)),
        _make_span("380.00", (380.0, 160.0, 440.0, 180.0)),
        _make_span("38,000", (500.0, 160.0, 560.0, 180.0)),
    ]

    tables, consumed = detect_borderless_tables(spans, consumed_indices=set())

    assert len(tables) == 1
    table = tables[0]
    assert table.metadata.get("kind") == "borderless_table"
    assert len(table.headers) == 4
    assert "Item Description" in table.headers[0]
    assert "Qty" in table.headers[1]
    assert len(table.rows) == 2
    assert "Steel Rods 10mm" in table.rows[0][0]
    assert "38,000" in table.rows[1][3]
    assert len(consumed) == 12


# ==============================================================================
# 7. Layout Reconstruction Gating by Profile
# ==============================================================================

def test_layout_reconstruction_profile_gating() -> None:
    """Proves tables are extracted ONLY in LAYOUT_PRESERVING and CUSTOM(preserve_layout=True)."""
    engine = RapidOCREngine()

    # Borderless table spans
    spans = [
        _make_span("Col A", (50.0, 50.0, 150.0, 70.0)),
        _make_span("Col B", (250.0, 50.0, 350.0, 70.0)),
        _make_span("Val 1", (50.0, 80.0, 150.0, 100.0)),
        _make_span("Val 2", (250.0, 80.0, 350.0, 100.0)),
    ]

    mock_output = MagicMock()
    mock_output.txts = [s.text for s in spans]
    mock_output.boxes = [
        [[s.bounding_box[0], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[3]],
         [s.bounding_box[0], s.bounding_box[3]]]
        for s in spans
    ]
    mock_output.scores = [0.95] * len(spans)
    engine._engine = lambda arr, **kw: mock_output

    test_img = Image.new("RGB", (400, 200), color="white")

    # 1. INSTANT -> No tables
    p_inst, _, _, _ = engine.ocr_page(test_img, 1, "inp_1", profile=ExecutionProfile.INSTANT)
    assert len(p_inst.tables) == 0

    # 2. ACCURATE -> No tables
    p_acc, _, _, _ = engine.ocr_page(test_img, 1, "inp_1", profile=ExecutionProfile.ACCURATE)
    assert len(p_acc.tables) == 0

    # 3. CUSTOM without preserve_layout -> No tables
    p_cust_off, _, _, _ = engine.ocr_page(
        test_img, 1, "inp_1", profile=ExecutionProfile.CUSTOM, custom_options={"preserve_layout": False}
    )
    assert len(p_cust_off.tables) == 0

    # 4. CUSTOM with preserve_layout=True -> Table extracted
    p_cust_on, _, _, _ = engine.ocr_page(
        test_img, 1, "inp_1", profile=ExecutionProfile.CUSTOM, custom_options={"preserve_layout": True}
    )
    assert len(p_cust_on.tables) == 1

    # 5. LAYOUT_PRESERVING -> Table extracted
    p_layout, _, _, _ = engine.ocr_page(test_img, 1, "inp_1", profile=ExecutionProfile.LAYOUT_PRESERVING)
    assert len(p_layout.tables) == 1
    assert p_layout.tables[0].headers == ("Col A", "Col B")
    assert p_layout.tables[0].rows == (("Val 1", "Val 2"),)


# ==============================================================================
# 8. Layout-Preserving DOCX Export
# ==============================================================================

def test_layout_preserving_docx_export(tmp_path: Path) -> None:
    """Proves end-to-end OCR execution in LAYOUT_PRESERVING generates a Word table (<w:tbl>) in DOCX."""
    img_path = tmp_path / "table_doc.png"
    img = Image.new("RGB", (600, 300), color="white")
    draw = ImageDraw.Draw(img)
    # Title outside table
    draw.text((50, 20), "Monthly Summary", fill="black")
    # Borderless table
    draw.text((50, 60), "Month", fill="black")
    draw.text((250, 60), "Units", fill="black")
    draw.text((50, 90), "January", fill="black")
    draw.text((250, 90), "1200", fill="black")
    draw.text((50, 120), "February", fill="black")
    draw.text((250, 120), "1450", fill="black")
    img.save(img_path)

    # Set up mock engine that returns title + table spans
    title_span = _make_span("Monthly Summary", (50.0, 20.0, 250.0, 45.0))
    table_spans = [
        _make_span("Month", (50.0, 60.0, 150.0, 80.0)),
        _make_span("Units", (250.0, 60.0, 350.0, 80.0)),
        _make_span("January", (50.0, 90.0, 150.0, 110.0)),
        _make_span("1200", (250.0, 90.0, 320.0, 110.0)),
        _make_span("February", (50.0, 120.0, 150.0, 140.0)),
        _make_span("1450", (250.0, 120.0, 320.0, 140.0)),
    ]
    all_spans = [title_span] + table_spans

    mock_output = MagicMock()
    mock_output.txts = [s.text for s in all_spans]
    mock_output.boxes = [
        [[s.bounding_box[0], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[3]],
         [s.bounding_box[0], s.bounding_box[3]]]
        for s in all_spans
    ]
    mock_output.scores = [0.95] * len(all_spans)

    engine = RapidOCREngine()
    engine._engine = lambda arr, **kw: mock_output

    cap = OCRCapability(engine=engine)
    ctx = ExecutionContext("run-docx-tbl", "req-docx-tbl", "t-1", "s-1")
    inp = InputRef("inp-docx-1", source_path=img_path, display_name="table_doc.png", size_bytes=img_path.stat().st_size)
    req = Request("req-docx-tbl", requirement="ocr", inputs=(inp,), profile=ExecutionProfile.LAYOUT_PRESERVING)

    result = cap.execute(req, ctx)
    assert isinstance(result, Result)

    # 1. PageData.tables must be populated
    doc = result.data
    assert len(doc.pages) == 1
    page = doc.pages[0]
    assert len(page.tables) == 1
    assert page.tables[0].headers == ("Month", "Units")

    # 2. DOCX artifact must contain <w:tbl>
    docx_payload = next(p for p in result.artifact_payloads if p.intent.media_type.endswith("document"))
    with zipfile.ZipFile(io.BytesIO(docx_payload.content)) as zf:
        xml_content = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tbl>" in xml_content or "<w:tbl " in xml_content, "DOCX must contain a Word table (<w:tbl>)"
        assert "Month" in xml_content
        assert "Units" in xml_content
        assert "January" in xml_content
        assert "1200" in xml_content


# ==============================================================================
# 9. Original Confidence & Text Evidence Invariance
# ==============================================================================

def test_original_confidence_and_evidence_invariance() -> None:
    """Proves layout reconstruction preserves original span confidence scores and text evidence."""
    spans = [
        _make_span("Sentence one.", (50.0, 50.0, 200.0, 70.0), conf=0.8876),
        _make_span("Sentence two.", (50.0, 75.0, 200.0, 95.0), conf=0.7432),
    ]

    engine = RapidOCREngine()
    mock_output = MagicMock()
    mock_output.txts = [s.text for s in spans]
    mock_output.boxes = [
        [[s.bounding_box[0], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[3]],
         [s.bounding_box[0], s.bounding_box[3]]]
        for s in spans
    ]
    mock_output.scores = [0.8876, 0.7432]
    engine._engine = lambda arr, **kw: mock_output

    test_img = Image.new("RGB", (300, 150), color="white")
    page_data, prov, conf, _ = engine.ocr_page(test_img, 1, "inp_1", profile=ExecutionProfile.LAYOUT_PRESERVING)

    # Spans must have identical factual confidences
    assert page_data.spans[0].confidence == pytest.approx(0.8876)
    assert page_data.spans[1].confidence == pytest.approx(0.7432)
    assert page_data.spans[0].text == "Sentence one."
    assert page_data.spans[1].text == "Sentence two."


# ==============================================================================
# 10. Multi-Column Layout Detection
# ==============================================================================

def test_detect_column_count_single_vs_multi() -> None:
    """Proves detect_column_count correctly differentiates single-column vs multi-column layouts."""
    # Single column: spans vertically stacked at similar horizontal start
    single_col_spans = [
        _make_span("First paragraph line one.", (50.0, 50.0, 350.0, 70.0)),
        _make_span("First paragraph line two.", (50.0, 75.0, 350.0, 95.0)),
        _make_span("Second paragraph line one.", (50.0, 110.0, 340.0, 130.0)),
        _make_span("Second paragraph line two.", (50.0, 135.0, 350.0, 155.0)),
    ]
    assert detect_column_count(single_col_spans) == 1

    # Two columns: left column (x: 50..220) and right column (x: 260..430) with cross-column header
    two_col_spans = [
        _make_span("ANNUAL REPORT AND STATEMENT", (50.0, 10.0, 430.0, 30.0)),
        _make_span("Left column line 1.", (50.0, 50.0, 220.0, 70.0)),
        _make_span("Left column line 2.", (50.0, 75.0, 220.0, 95.0)),
        _make_span("Right column line 1.", (260.0, 50.0, 430.0, 70.0)),
        _make_span("Right column line 2.", (260.0, 75.0, 430.0, 95.0)),
    ]
    assert detect_column_count(two_col_spans) == 2


# ==============================================================================
# 11. Ragged Row and Spanning Cell Warning Detection
# ==============================================================================

def test_ragged_table_warning_emission() -> None:
    """Proves RapidOCREngine emits LAYOUT_TABLE_ROW_RAGGED warning when a table has irregular row widths."""
    engine = RapidOCREngine()

    # Create dummy spans
    spans = [
        _make_span("Cell 1", (50.0, 50.0, 150.0, 70.0)),
        _make_span("Cell 2", (160.0, 50.0, 260.0, 70.0)),
    ]
    mock_output = MagicMock()
    mock_output.txts = [s.text for s in spans]
    mock_output.boxes = [
        [[s.bounding_box[0], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[1]],
         [s.bounding_box[2], s.bounding_box[3]],
         [s.bounding_box[0], s.bounding_box[3]]]
        for s in spans
    ]
    mock_output.scores = [0.95, 0.95]
    engine._engine = lambda arr, **kw: mock_output

    # Mock reconstruct_layout to return a table with ragged rows
    ragged_table = TableData(
        name="ragged_tbl",
        headers=("Col A", "Col B", "Col C"),
        rows=(
            ("val1", "val2"),  # Missing 3rd column -> ragged!
        ),
        metadata={"has_spanning_cells": False},
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "sarathi.shakti.ocr.engine.coordinator.reconstruct_layout",
            lambda img, sps, preserve_layout=True: ("Table Text", (ragged_table,)),
        )

        test_img = Image.new("RGB", (300, 150), color="white")
        _, _, _, warnings = engine.ocr_page(test_img, 1, "inp_ragged", profile=ExecutionProfile.LAYOUT_PRESERVING)

        ragged_warns = [w for w in warnings if w.code == "LAYOUT_TABLE_ROW_RAGGED"]
        assert len(ragged_warns) >= 1
        assert "ragged_tbl" in ragged_warns[0].message


# ==============================================================================
# 12. Scanned Image Arbitration in Usable Page Checks
# ==============================================================================

def test_is_usable_page_scanned_image_arbitration() -> None:
    """Proves _is_usable_page routes pages with high image coverage and sparse text to OCR."""
    # Normal page with plenty of text -> usable native page
    normal_page = PageData(
        page_number=1,
        text="This is a long document page containing several sentences of extracted native text.",
        metadata={"image_coverage": 0.10},
    )
    assert _is_usable_page(normal_page) is True

    # Page explicitly flagged as scanned image -> not usable native text
    scanned_flagged_page = PageData(
        page_number=1,
        text="A few words.",
        metadata={"is_scanned_image": True},
    )
    assert _is_usable_page(scanned_flagged_page) is False

    # Page with 85% image coverage and sparse OCR/ghost text (< 30 chars) -> not usable native text
    hybrid_scanned_page = PageData(
        page_number=1,
        text="Sparse artifact.",
        metadata={"image_coverage": 0.85},
    )
    assert _is_usable_page(hybrid_scanned_page) is False

    # Page with 85% image coverage but rich native text (e.g. text overlaying image) -> usable native text
    dense_text_with_bg = PageData(
        page_number=1,
        text="This page has a background image but contains a complete article of native extractable text content.",
        metadata={"image_coverage": 0.85},
    )
    assert _is_usable_page(dense_text_with_bg) is True
