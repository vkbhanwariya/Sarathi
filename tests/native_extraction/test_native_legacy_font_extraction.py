"""Unit tests for Native Extraction with embedded Hindi legacy Devanagari font conversion."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.native_extraction import NativeExtractionCapability


@pytest.fixture
def capability() -> NativeExtractionCapability:
    return NativeExtractionCapability()


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-legacy-font-1",
        request_id="req-legacy-font-1",
        trace_id="tr-1",
        span_id="sp-1",
    )


def test_native_extraction_krutidev_pdf_auto_converted(
    capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
) -> None:
    """A PDF with KrutiDev legacy Devanagari text is automatically converted to Unicode Devanagari by default."""
    pdf_path = tmp_path / "krutidev_doc.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    # "Hkkjr ljdkj fnYyh" -> "भारत सरकार दिल्ली" in KrutiDev 010
    page.insert_text((72, 72), "Hkkjr ljdkj fnYyh\nLVsV cSad")
    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/ABCDEF+KrutiDev010")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    req = Request(
        request_id="req-kd-1",
        requirement="read_native",
        inputs=(
            InputRef(
                input_id="inp-kd-1",
                source_path=pdf_path,
                display_name="krutidev_doc.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
    )

    res = capability.execute(req, context)
    assert isinstance(res, Result)
    assert res.next_requirement is None

    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    # Converted text should contain clean Unicode Devanagari
    assert "भारत सरकार दिल्ली" in doc.text or "भारत सरकार दिल्ली" in doc.pages[0].text

    # Artifact payload verification
    txt_payload = next(p for p in res.artifact_payloads if p.intent.role == "extracted_text")
    txt_content = txt_payload.content.decode("utf-8")
    assert "भारत सरकार दिल्ली" in txt_content

    # Provenance verification
    conv_prov = [p for p in res.provenance if p.capability_id == "font_conversion"]
    assert len(conv_prov) == 1
    assert conv_prov[0].stage == "convert_legacy_fonts"


def test_native_extraction_krutidev_pdf_conversion_disabled(
    capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
) -> None:
    """When convert_legacy_fonts=False, legacy typewriter text is preserved verbatim."""
    pdf_path = tmp_path / "raw_krutidev.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    page.insert_text((72, 72), "Hkkjr ljdkj fnYyh")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    req = Request(
        request_id="req-kd-2",
        requirement="read_native",
        inputs=(
            InputRef(
                input_id="inp-kd-2",
                source_path=pdf_path,
                display_name="raw_krutidev.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
        custom_options={"convert_legacy_fonts": False},
    )

    res = capability.execute(req, context)
    assert isinstance(res, Result)

    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    assert "Hkkjr ljdkj fnYyh" in doc.text or "Hkkjr ljdkj fnYyh" in doc.pages[0].text
    assert "भारत सरकार दिल्ली" not in doc.text

    # No font conversion provenance
    assert not any(p.capability_id == "font_conversion" for p in res.provenance)


def test_native_extraction_standard_english_pdf_unaffected(
    capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
) -> None:
    """Standard English / modern documents pass through cleanly without modification or warnings."""
    pdf_path = tmp_path / "english_doc.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    page.insert_text((72, 72), "Annual Financial Report 2026\nRevenue: $1,000,000")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    req = Request(
        request_id="req-en-1",
        requirement="read_native",
        inputs=(
            InputRef(
                input_id="inp-en-1",
                source_path=pdf_path,
                display_name="english_doc.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
        custom_options={"convert_legacy_fonts": True},
    )

    res = capability.execute(req, context)
    assert isinstance(res, Result)

    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    assert "Annual Financial Report 2026" in doc.text
    # No spurious font conversion warnings
    assert not any(w.code == "NO_LEGACY_FONT_DETECTED" for w in res.warnings)
    assert not any(p.capability_id == "font_conversion" for p in res.provenance)


def test_native_extraction_devlys_pdf_auto_converted(
    capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
) -> None:
    """PDF with embedded DevLys 010 legacy font is converted to Unicode Devanagari."""
    pdf_path = tmp_path / "devlys_doc.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    page.insert_text((72, 72), "Hkkjr ljdkj")
    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/XYZABC+DevLys010")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    req = Request(
        request_id="req-dl-1",
        requirement="read_native",
        inputs=(
            InputRef(
                input_id="inp-dl-1",
                source_path=pdf_path,
                display_name="devlys_doc.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
    )

    res = capability.execute(req, context)
    assert isinstance(res, Result)
    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    assert "भारत सरकार" in doc.text or "भारत सरकार" in doc.pages[0].text


def test_native_extraction_chanakya_pdf_auto_converted(
    capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
) -> None:
    """PDF with embedded Chanakya legacy font is converted to Unicode Devanagari."""
    pdf_path = tmp_path / "chanakya_doc.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    # '·' -> 'क', '¥æ' -> 'आ'
    page.insert_text((72, 72), "¥æ ·")
    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/SUBSET+Chanakya")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    req = Request(
        request_id="req-ch-1",
        requirement="read_native",
        inputs=(
            InputRef(
                input_id="inp-ch-1",
                source_path=pdf_path,
                display_name="chanakya_doc.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
    )

    res = capability.execute(req, context)
    assert isinstance(res, Result)
    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    assert "आ क" in doc.text or "आ क" in doc.pages[0].text


def test_native_extraction_legacy_font_chains_to_statutory(
    capability: NativeExtractionCapability, context: ExecutionContext, tmp_path: Path
) -> None:
    """When statutory extraction is requested alongside legacy font conversion, statutory chains on clean Unicode text."""
    pdf_path = tmp_path / "legal_krutidev.pdf"
    doc_pdf = pymupdf.open()
    page = doc_pdf.new_page(width=595, height=842)
    page.insert_text((72, 72), "Hkkjr ljdkj fnYyh")
    fonts = doc_pdf.get_page_fonts(0)
    if fonts:
        doc_pdf.xref_set_key(fonts[0][0], "BaseFont", "/ABCDEF+KrutiDev010")
    doc_pdf.save(str(pdf_path))
    doc_pdf.close()

    req = Request(
        request_id="req-leg-stat-1",
        requirement="read_native",
        inputs=(
            InputRef(
                input_id="inp-leg-stat-1",
                source_path=pdf_path,
                display_name="legal_krutidev.pdf",
                size_bytes=pdf_path.stat().st_size,
            ),
        ),
        custom_options={"statutory": True, "convert_legacy_fonts": True},
    )

    res = capability.execute(req, context)
    assert isinstance(res, Result)
    # Next requirement is statutory
    assert res.next_requirement == "statutory"
    # Document text is already converted to Unicode Devanagari for statutory processing
    doc = res.data
    assert isinstance(doc, CanonicalDocument)
    assert "भारत सरकार दिल्ली" in doc.text or "भारत सरकार दिल्ली" in doc.pages[0].text

