"""Integration Tests for Vector Drawing PDF Table Extraction (Phase 5)."""

from __future__ import annotations

import pymupdf

from sarathi.shakti.native_extraction.readers.pdf import read_pdf


def _build_vector_table_pdf() -> bytes:
    """Construct an in-memory PDF with vector line strokes forming a 2-row x 3-col table."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Define table grid coordinates: 3 rows (y = 100, 140, 180), 4 cols (x = 50, 150, 250, 350)
    xs = [50.0, 150.0, 250.0, 350.0]
    ys = [100.0, 140.0, 180.0]

    # Draw horizontal lines
    for y in ys:
        page.draw_line(pymupdf.Point(xs[0], y), pymupdf.Point(xs[-1], y), color=(0, 0, 0), width=1)

    # Draw vertical lines
    for x in xs:
        page.draw_line(pymupdf.Point(x, ys[0]), pymupdf.Point(x, ys[-1]), color=(0, 0, 0), width=1)

    # Insert cell texts
    # Header row (y between 100 and 140)
    page.insert_text(pymupdf.Point(60, 125), "Header A", fontsize=11)
    page.insert_text(pymupdf.Point(160, 125), "Header B", fontsize=11)
    page.insert_text(pymupdf.Point(260, 125), "Header C", fontsize=11)

    # Data row (y between 140 and 180)
    page.insert_text(pymupdf.Point(60, 165), "Data 1", fontsize=10)
    page.insert_text(pymupdf.Point(160, 165), "Data 2", fontsize=10)
    page.insert_text(pymupdf.Point(260, 165), "Data 3", fontsize=10)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_vector_table_extraction_reconstructs_grid() -> None:
    """Verify vector drawing lines and text cells are extracted into TableData."""
    pdf_bytes = _build_vector_table_pdf()
    doc, provs, warns = read_pdf(pdf_bytes, input_id="vector_table_test")

    assert len(doc.tables) >= 1
    table = doc.tables[0]
    assert len(table.headers) == 3
    assert "Header" in table.headers[0] and "A" in table.headers[0]
    assert "Header" in table.headers[1] and "B" in table.headers[1]
    assert "Header" in table.headers[2] and "C" in table.headers[2]

    assert len(table.rows) == 1
    row0 = table.rows[0]
    assert "Data" in row0[0] and "1" in row0[0]
    assert "Data" in row0[1] and "2" in row0[1]
    assert "Data" in row0[2] and "3" in row0[2]

    # Table promoted to page as well
    assert len(doc.pages[0].tables) >= 1
    assert doc.pages[0].tables[0] is table
    assert table.metadata.get("bounding_box") is not None
