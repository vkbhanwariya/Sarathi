"""Unit & Integration Tests for Bandhan Bank Statements (PDF, Excel, and HTML-disguised XLS).

Validates:
1. Bandhan profile detection and metadata extraction across all formats.
2. Extraction of all transactions with 0 balance or continuity errors.
3. Multi-page narration wrap stitching across physical page breaks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.sankalpa import ExecutionContext, InputRef, Request
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability

_BANDHAN_DIR = Path("Input/Bandhan")
_XLS_FILE = _BANDHAN_DIR / "20100018588850 SOA EXCEL.xls"
_XLSX_FILE = _BANDHAN_DIR / "Statement in Excel.xlsx"
_PDF_SOA = _BANDHAN_DIR / "pdf/SOA.pdf"
_PDF_LARGE = _BANDHAN_DIR / "pdf/Statement-20200053002591.pdf"


@pytest.mark.skipif(not _XLS_FILE.exists(), reason="Input/Bandhan XLS statement not present")
def test_bandhan_excel_fmt1_html_disguised() -> None:
    data = _XLS_FILE.read_bytes()
    in_ref = InputRef(input_id="in-xls-1", source_path=_XLS_FILE, display_name=_XLS_FILE.name, size_bytes=len(data))
    req = Request(request_id="req-bandhan-xls", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-1", request_id="req-bandhan-xls", trace_id="tr-1", span_id="sp-1")

    native_res = NativeExtractionCapability().execute(req, ctx)
    doc = native_res.data
    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "Bandhan Bank Limited"
    assert det.matched_profile == "bandhan_excel_fmt1"
    assert det.account_identity is not None
    assert det.account_identity.masked_account_number.endswith("8850")

    bank_res = BankStatementCapability().execute(req, ctx, native_res)
    stmt = bank_res.data.statements[0]
    assert stmt.bank_profile == "bandhan_excel_fmt1"
    assert len(stmt.transactions) == 45
    assert stmt.status == "valid"
    assert len(stmt.issues) == 0


@pytest.mark.skipif(not _XLSX_FILE.exists(), reason="Input/Bandhan XLSX statement not present")
def test_bandhan_excel_fmt2() -> None:
    data = _XLSX_FILE.read_bytes()
    in_ref = InputRef(input_id="in-xlsx-1", source_path=_XLSX_FILE, display_name=_XLSX_FILE.name, size_bytes=len(data))
    req = Request(request_id="req-bandhan-xlsx", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-2", request_id="req-bandhan-xlsx", trace_id="tr-2", span_id="sp-2")

    native_res = NativeExtractionCapability().execute(req, ctx)
    doc = native_res.data
    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "Bandhan Bank Limited"
    assert det.matched_profile == "bandhan_excel_fmt2"
    assert det.account_identity is not None
    assert det.account_identity.masked_account_number.endswith("2591")

    bank_res = BankStatementCapability().execute(req, ctx, native_res)
    stmt = bank_res.data.statements[0]
    assert stmt.bank_profile == "bandhan_excel_fmt2"
    assert len(stmt.transactions) == 1101
    assert stmt.status == "valid"
    assert len(stmt.issues) == 0


@pytest.mark.skipif(not _PDF_SOA.exists(), reason="Input/Bandhan PDF SOA not present")
def test_bandhan_pdf_fmt1_short() -> None:
    data = _PDF_SOA.read_bytes()
    in_ref = InputRef(input_id="in-pdf-1", source_path=_PDF_SOA, display_name=_PDF_SOA.name, size_bytes=len(data))
    req = Request(request_id="req-bandhan-pdf-1", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-3", request_id="req-bandhan-pdf-1", trace_id="tr-3", span_id="sp-3")

    native_res = NativeExtractionCapability().execute(req, ctx)
    doc = native_res.data
    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "Bandhan Bank Limited"
    assert det.matched_profile == "bandhan_pdf_fmt1"
    assert det.account_identity is not None
    assert det.account_identity.masked_account_number.endswith("8850")

    bank_res = BankStatementCapability().execute(req, ctx, native_res)
    stmt = bank_res.data.statements[0]
    assert stmt.bank_profile == "bandhan_pdf_fmt1"
    assert len(stmt.transactions) == 45
    assert stmt.status == "valid"
    assert len(stmt.issues) == 0


@pytest.mark.skipif(not _PDF_LARGE.exists(), reason="Input/Bandhan PDF multi-page not present")
def test_bandhan_pdf_fmt1_multipage() -> None:
    data = _PDF_LARGE.read_bytes()
    in_ref = InputRef(input_id="in-pdf-2", source_path=_PDF_LARGE, display_name=_PDF_LARGE.name, size_bytes=len(data))
    req = Request(request_id="req-bandhan-pdf-2", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-4", request_id="req-bandhan-pdf-2", trace_id="tr-4", span_id="sp-4")

    native_res = NativeExtractionCapability().execute(req, ctx)
    doc = native_res.data
    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "Bandhan Bank Limited"
    assert det.matched_profile == "bandhan_pdf_fmt1"
    assert det.account_identity is not None
    assert det.account_identity.masked_account_number.endswith("2591")

    bank_res = BankStatementCapability().execute(req, ctx, native_res)
    stmt = bank_res.data.statements[0]
    assert stmt.bank_profile == "bandhan_pdf_fmt1"
    assert len(stmt.transactions) == 1101
    assert stmt.status == "valid"
    assert len(stmt.issues) == 0
