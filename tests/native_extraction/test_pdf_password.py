"""Tests for password-protected PDF handling across native extraction and rasterization."""

from __future__ import annotations

import pymupdf
import pytest

from sarathi.sankalpa import ExecutionContext, ExecutionProfile, InputRef, Request
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability
from sarathi.shakti.native_extraction.readers.pdf import read_pdf
from sarathi.shakti.ocr.engine.rasterize import (
    extract_single_page_image,
    get_page_count_from_bytes,
)


@pytest.fixture
def encrypted_pdf_bytes() -> bytes:
    """Create a temporary 1-page AES-256 encrypted PDF in memory."""
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 100), "Confidential Secret Record 998877")
    pdf_bytes = doc.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="bankpass42",
        owner_pw="bankowner42",
    )
    doc.close()
    return pdf_bytes


def test_read_pdf_without_password_warns(encrypted_pdf_bytes: bytes) -> None:
    doc, provs, warns = read_pdf(encrypted_pdf_bytes, input_id="inp-enc-1")
    assert any(w.code == "PDF_PASSWORD_REQUIRED" for w in warns)
    assert "Confidential" not in doc.text


def test_read_pdf_with_wrong_password_warns(encrypted_pdf_bytes: bytes) -> None:
    doc, provs, warns = read_pdf(encrypted_pdf_bytes, input_id="inp-enc-2", password="wrongpassword")
    assert any(w.code == "PDF_AUTHENTICATION_FAILED" for w in warns)
    assert "Confidential" not in doc.text


def test_read_pdf_with_correct_password_succeeds(encrypted_pdf_bytes: bytes) -> None:
    doc, provs, warns = read_pdf(encrypted_pdf_bytes, input_id="inp-enc-3", password="bankpass42")
    assert not any(w.code in ("PDF_PASSWORD_REQUIRED", "PDF_AUTHENTICATION_FAILED") for w in warns)
    assert "Confidential Secret Record 998877" in doc.text
    assert len(doc.pages) == 1


def test_rasterize_with_correct_password(encrypted_pdf_bytes: bytes) -> None:
    page_count = get_page_count_from_bytes(encrypted_pdf_bytes, password="bankpass42")
    assert page_count == 1

    img = extract_single_page_image(encrypted_pdf_bytes, page_number=1, password="bankpass42")
    assert img is not None
    assert img.size[0] > 0


def test_native_extraction_capability_with_request_passwords(encrypted_pdf_bytes: bytes, tmp_path) -> None:
    file_path = tmp_path / "statement.pdf"
    file_path.write_bytes(encrypted_pdf_bytes)

    inp = InputRef(
        input_id="inp-stat",
        source_path=file_path,
        media_type="application/pdf",
        display_name="statement.pdf",
        size_bytes=len(encrypted_pdf_bytes),
    )
    request = Request(
        request_id="req-enc-test",
        requirement="read_native",
        inputs=[inp],
        profile=ExecutionProfile.INSTANT,
        custom_options={"passwords": {"statement.pdf": "bankpass42"}},
    )
    context = ExecutionContext(run_id="run-enc-1", request_id="req-enc-test", trace_id="t-1", span_id="s-1")
    cap = NativeExtractionCapability()

    result = cap.execute(request, context)
    assert result.data is not None
    doc = result.data if not isinstance(result.data, (list, tuple)) else result.data[0]
    assert "Confidential Secret Record 998877" in doc.text
