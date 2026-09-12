"""Unit tests for GNN-powered PDF layout analysis via pymupdf-layout."""

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
    Request,
    Result,
)
from sarathi.shakti.native_extraction import NativeExtractionCapability
from sarathi.shakti.native_extraction.readers.pdf import read_pdf
from sarathi.shakti.native_extraction.readers.pdf_layout import (
    is_layout_package_available,
    read_pdf_with_layout,
)


@pytest.fixture
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
    """Verify is_layout_package_available returns True when pymupdf-layout is installed."""
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

    # Verify provenance records GNN model execution
    assert len(provs) == 1
    p = provs[0]
    assert p.evidence["reader"] == "pymupdf_layout"
    assert p.evidence["model"] == "BoxRFDGNN"
    assert p.evidence["layout_elements_count"] > 0


def test_read_pdf_layout_dispatch(sample_pdf_bytes: bytes) -> None:
    """read_pdf dispatches to read_pdf_with_layout when use_layout=True."""
    doc, provs, warns = read_pdf(sample_pdf_bytes, "inp-dispatch", use_layout=True)

    assert isinstance(doc, CanonicalDocument)
    assert any(p.evidence.get("reader") == "pymupdf_layout" for p in provs)
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
    """read_pdf gracefully falls back to standard PyMuPDF if GNN execution raises an unexpected error."""
    with patch(
        "sarathi.shakti.native_extraction.readers.pdf_layout.read_pdf_with_layout",
        side_effect=RuntimeError("GNN inference failed unexpectedly"),
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

    # Provenance confirms pymupdf_layout was used
    assert any(p.evidence.get("reader") == "pymupdf_layout" for p in res.provenance)


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
