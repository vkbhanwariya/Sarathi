"""Unit & Integration Tests for State Bank of India (SBI) PDF Statements.

Validates:
1. SBI profile detection and metadata extraction (Account No, Account Holder, IFSC).
2. Multi-page physical table split-row stitching across 324 pages.
3. Extraction of all 459 transactions with 0 balance or continuity errors.
4. Full financial reconciliation: Opening Balance (0.00) to Closing Balance (1657.58).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from sarathi.sankalpa import ExecutionContext, InputRef, Request, Result
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.native_extraction.readers.pdf import read_pdf

_SBI_FILE = Path("Input/SBI/Account_Statement_from_inception_PDF_or_Excel_format_1778911311573_1778911311573_Account_Statement_1.pdf")


@pytest.mark.skipif(not _SBI_FILE.exists(), reason="Input/SBI statement not present")
def test_sbi_statement_detection_and_extraction() -> None:
    data = _SBI_FILE.read_bytes()
    doc, _, _ = read_pdf(data=data, input_id="sbi_test", source_path=_SBI_FILE)

    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "State Bank of India"
    assert det.matched_profile == "sbi_pdf_fmt1"
    assert det.account_identity is not None
    assert det.account_identity.account_holder == "RAMAWATAR RATHI"
    assert det.account_identity.masked_account_number.endswith("5968")

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-sbi-01",
        source_path=_SBI_FILE,
        display_name=_SBI_FILE.name,
        size_bytes=len(data),
    )
    req = Request(request_id="req-sbi-01", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-sbi-01", request_id="req-sbi-01", trace_id="tr-1", span_id="sp-1")
    res = cap.execute(req, ctx, Result(data=doc))

    consolidation = res.data
    assert consolidation.total_transactions == 459
    assert len(consolidation.statements) == 1

    stmt = consolidation.statements[0]
    assert stmt.bank_name == "State Bank of India"
    assert stmt.bank_profile == "sbi_pdf_fmt1"
    assert stmt.account_identity is not None
    assert stmt.account_identity.account_holder == "RAMAWATAR RATHI"
    assert stmt.account_identity.masked_account_number.endswith("5968")
    assert stmt.opening_balance == Decimal("0.00")
    assert stmt.closing_balance == Decimal("1657.58")
    assert stmt.status == "valid"
    assert len(stmt.issues) == 0

    first_tx = stmt.transactions[0]
    assert first_tx.credit == Decimal("500.00")
    assert first_tx.running_balance == Decimal("500.00")

    last_tx = stmt.transactions[-1]
    assert last_tx.credit == Decimal("1500.00")
    assert last_tx.running_balance == Decimal("1657.58")
