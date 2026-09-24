"""Unit tests for PDF layout analysis via xberg."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    ProvenanceRecord,
    Request,
    Result,
)
from sarathi.shakti.native_extraction import NativeExtractionCapability
from sarathi.shakti.native_extraction.readers.pdf import read_pdf
from sarathi.shakti.native_extraction.readers.pdf_layout import (
    is_layout_package_available,
    read_pdf_with_layout,
)

pytestmark = pytest.mark.layout


@pytest.fixture(scope="module")
def sample_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Quarterly Financial Analysis", fontsize=18)
    page.insert_text((72, 110), "Revenue increased by 14% year-over-year.", fontsize=11)
    page.insert_text((72, 130), "Operating margin remained steady at 28%.", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def test_layout_package_available() -> None:
    """Verify is_layout_package_available returns True when layout engine (xberg) is installed."""
    assert is_layout_package_available() is True


def test_read_pdf_with_layout_extracts_headings_and_semantics(sample_pdf_bytes: bytes) -> None:
    """read_pdf_with_layout extracts semantic layout classes and topological spans."""
    doc, provs, warns = read_pdf_with_layout(sample_pdf_bytes, "inp-test-layout")

    assert isinstance(doc, CanonicalDocument)
    assert len(doc.pages) == 1
    page = doc.pages[0]

    # Verify spans contain layout metadata
    assert len(page.spans) >= 2
    assert any(s.metadata.get("layout_class") for s in page.spans)
    assert any(s.metadata.get("is_heading") for s in page.spans)

    # Verify provenance records layout engine execution
    assert len(provs) == 1
    p = provs[0]
    assert p.evidence["reader"] == "xberg_layout"
    assert p.evidence["layout_elements_count"] > 0


def test_read_pdf_layout_dispatch(sample_pdf_bytes: bytes) -> None:
    """read_pdf dispatches to read_pdf_with_layout when use_layout=True."""
    mock_doc = CanonicalDocument(document_id="inp-dispatch", text="Sample", pages=())
    mock_prov = ProvenanceRecord(evidence={"reader": "xberg_layout"})
    with patch(
        "sarathi.shakti.native_extraction.readers.pdf_layout.read_pdf_with_layout",
        return_value=(mock_doc, [mock_prov], []),
    ) as mock_layout:
        doc, provs, warns = read_pdf(sample_pdf_bytes, "inp-dispatch", use_layout=True)
        assert mock_layout.called
        assert doc is mock_doc
        assert any(p.evidence.get("reader") == "xberg_layout" for p in provs)
        assert not any(w.code == "LAYOUT_PACKAGE_UNAVAILABLE" for w in warns)


def test_read_pdf_layout_fallback_when_unavailable(sample_pdf_bytes: bytes) -> None:
    """read_pdf gracefully falls back to standard PyMuPDF when layout package is unavailable."""
    with patch(
        "sarathi.shakti.native_extraction.readers.pdf_layout.is_layout_package_available",
        return_value=False,
    ):
        doc, provs, warns = read_pdf(sample_pdf_bytes, "inp-fallback", use_layout=True)

    assert isinstance(doc, CanonicalDocument)
    # Standard reader evidence
    assert any(p.evidence.get("reader") == "pymupdf" for p in provs)
    # Clean warning emitted
    assert any(w.code == "LAYOUT_PACKAGE_UNAVAILABLE" for w in warns)
    assert "Quarterly Financial Analysis" in doc.text


def test_read_pdf_layout_fallback_on_runtime_error(sample_pdf_bytes: bytes) -> None:
    """read_pdf gracefully falls back to standard PyMuPDF if layout execution raises an unexpected error."""
    with patch(
        "sarathi.shakti.native_extraction.readers.pdf_layout.read_pdf_with_layout",
        side_effect=RuntimeError("Layout extraction failed unexpectedly"),
    ):
        doc, provs, warns = read_pdf(sample_pdf_bytes, "inp-err-fallback", use_layout=True)

    assert isinstance(doc, CanonicalDocument)
    assert any(w.code == "LAYOUT_ANALYSIS_FAILED" for w in warns)
    assert "Quarterly Financial Analysis" in doc.text


def test_native_extraction_capability_with_layout_analysis(tmp_path: Path) -> None:
    """NativeExtractionCapability invokes layout analysis when requested via custom_options or profile."""
    pdf_path = tmp_path / "layout_doc.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    page.insert_text((72, 72), "Executive Summary", fontsize=20)
    page.insert_text((72, 120), "Project Sarathi automates local document processing.", fontsize=12)
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    cap = NativeExtractionCapability()
    ctx = ExecutionContext(run_id="run-lay-1", request_id="req-lay-1", trace_id="t-1", span_id="s-1")

    req = Request(
        request_id="req-lay-1",
        requirement="read_native",
        profile=ExecutionProfile.LAYOUT_PRESERVING,
        inputs=(
            InputRef(
                input_id="inp-lay-1",
                source_path=pdf_path,
                display_name="layout_doc.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
        custom_options={"layout_analysis": True},
    )

    res = cap.execute(req, ctx)
    assert isinstance(res, Result)
    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    assert "Executive Summary" in doc.text

    # Provenance confirms layout engine was used
    assert any(p.evidence.get("reader") == "xberg_layout" for p in res.provenance)


def test_spatial_word_reconstruction_and_paragraph_breaks() -> None:
    """Verify that multi-span words and paragraph boundaries are accurately spaced."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "Statutory Audit Notice", fontsize=16)
    page.insert_text((72, 110), "Section 1: ", fontname="helv", fontsize=12)
    page.insert_text((135, 110), "Scope of Review", fontname="times-roman", fontsize=12)
    page.insert_text((72, 140), "First paragraph line one.", fontsize=10)
    page.insert_text((72, 155), "First paragraph line two.", fontsize=10)
    page.insert_text((72, 190), "Second paragraph starts here.", fontsize=10)
    data = doc.tobytes()
    doc.close()

    cdoc, _, _ = read_pdf_with_layout(data, "inp-spacing")
    assert "Statutory Audit Notice" in cdoc.text
    assert "Section 1: Scope of Review" in cdoc.text
    assert "First paragraph line one.\nFirst paragraph line two." in cdoc.text
    assert "\n\nSecond paragraph starts here." in cdoc.text


def test_running_header_footer_detection_and_clean_separation() -> None:
    """Verify that recurring running headers and footers are separated into metadata and omitted from clean text."""
    doc = pymupdf.open()
    for p_num in (1, 2):
        page = doc.new_page(width=595, height=842)
        # Running header at top margin (y=40)
        page.insert_text((72, 40), f"[2026:RJ-JP:18881][CRLMP-4154/2023] Page {p_num} of 2", fontsize=9)
        # Body text
        page.insert_text((72, 150), f"This is the judicial narrative on page {p_num}.", fontsize=12)
        # Running footer at bottom margin (y=800)
        page.insert_text((72, 800), "Confidential Court Document", fontsize=8)
    data = doc.tobytes()
    doc.close()

    # 1. Standard reader with skip_header_footer=True
    cdoc, _, _ = read_pdf(data, "inp-hdr-std", skip_header_footer=True)
    assert len(cdoc.pages) == 2
    for p_idx, p in enumerate(cdoc.pages, 1):
        assert f"This is the judicial narrative on page {p_idx}." in p.text
        # Running header and footer must NOT pollute the continuous body narrative
        assert "[2026:RJ-JP:18881]" not in p.text
        assert "Confidential Court Document" not in p.text
        # Header and footer must be captured in page metadata
        assert "[2026:RJ-JP:18881]" in str(p.metadata.get("header", ""))
        assert "Confidential Court Document" in str(p.metadata.get("footer", ""))

    # 2. Standard reader with skip_header_footer=False retains headers in body text
    cdoc_raw, _, _ = read_pdf(data, "inp-hdr-raw", skip_header_footer=False)
    assert any("[2026:RJ-JP:18881]" in p.text for p in cdoc_raw.pages)


def test_read_pdf_with_layout_multi_page_parallel_ordering() -> None:
    """Verify that multi-page layout analysis runs in parallel and preserves exact page ordering."""
    doc = pymupdf.open()
    total_test_pages = 3
    for p_num in range(1, total_test_pages + 1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Header Section Title Page {p_num}", fontsize=16)
        page.insert_text((72, 120), f"Body paragraph content for page number {p_num}.", fontsize=11)
    data = doc.tobytes()
    doc.close()

    cdoc, provs, warns = read_pdf_with_layout(data, "inp-multi-layout")
    assert isinstance(cdoc, CanonicalDocument)
    assert len(cdoc.pages) == total_test_pages
    assert len(provs) == total_test_pages

    # Strictly verify 1..N order of pages and content
    for idx, page in enumerate(cdoc.pages):
        expected_page_num = idx + 1
        assert page.page_number == expected_page_num
        assert f"Header Section Title Page {expected_page_num}" in page.text
        assert f"Body paragraph content for page number {expected_page_num}." in page.text

    # Verify provenance ordering
    for idx, prov in enumerate(provs):
        assert prov.page_number == idx + 1
        assert prov.evidence["page_count"] == total_test_pages


def test_read_document_with_xberg_raises_dosh_error_on_failure() -> None:
    """Xberg reader raises DoshError when extraction fails so callers can fallback."""
    from sarathi.dosh import DoshError
    from sarathi.shakti.native_extraction.readers.xberg_reader import read_document_with_xberg

    with patch("xberg.extract", side_effect=RuntimeError("Rust parser corrupted")):
        with pytest.raises(DoshError) as exc_info:
            read_document_with_xberg(b"invalid data", "inp-fail")
        assert "Xberg document extraction failed" in str(exc_info.value)


def test_read_document_with_xberg_confidence_none_and_skip_header_footer() -> None:
    """Spans have confidence=None (no fake defaults) and skip_header_footer extracts metadata."""
    from sarathi.shakti.native_extraction.readers.xberg_reader import read_document_with_xberg

    doc = pymupdf.open()
    for p_num in (1, 2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 40), f"Annual Report 2026 Page {p_num}", fontsize=9)
        page.insert_text((72, 150), f"Body paragraph for page {p_num}.", fontsize=12)
        page.insert_text((72, 800), "Confidential Internal Audit", fontsize=8)
    data = doc.tobytes()
    doc.close()

    cdoc, _, _ = read_document_with_xberg(data, "inp-hf-conf", skip_header_footer=True)
    assert len(cdoc.pages) == 2
    for p in cdoc.pages:
        for span in p.spans:
            assert span.confidence is None
        assert "Annual Report 2026" not in p.text
        assert "Confidential Internal Audit" not in p.text
        assert "Annual Report 2026" in str(p.metadata.get("header", ""))
        assert "Confidential Internal Audit" in str(p.metadata.get("footer", ""))


def test_xberg_header_suppression_preserves_changing_financial_content() -> None:
    """Verify that lines with changing financial amounts (e.g. Amount due 100 vs Amount due 200)

    are never suppressed as repeated headers across pages.
    """
    from sarathi.shakti.native_extraction.readers.xberg_reader import read_document_with_xberg

    doc = pymupdf.open()
    # Page 1
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((72, 50), "Amount due 100", fontsize=11)
    page1.insert_text((72, 120), "Line item 1 details", fontsize=10)

    # Page 2
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((72, 50), "Amount due 200", fontsize=11)
    page2.insert_text((72, 120), "Line item 2 details", fontsize=10)

    data = doc.tobytes()
    doc.close()

    cdoc, _, _ = read_document_with_xberg(data, "inp-fin-header", skip_header_footer=True)
    assert len(cdoc.pages) == 2
    assert "Amount due 100" in cdoc.pages[0].text
    assert "Amount due 200" in cdoc.pages[1].text
