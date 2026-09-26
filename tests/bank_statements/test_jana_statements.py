"""Unit & Integration Tests for Jana Small Finance Bank PDF Statements.

Validates:
1. Jana SFB profile detection and metadata extraction (Account No, Account Holder, IFSC).
2. Borderless multi-page fixed-column reconstruction across 9 pages.
3. Extraction of all 87 transactions with 0 balance or continuity errors.
4. Full financial reconciliation: Opening Balance (0.00) + Credits (984,114.38) - Debits (984,084.00) == Closing Balance (30.38).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from sarathi.sankalpa import ExecutionContext, InputRef, Request, Result
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.native_extraction.readers.pdf import read_pdf

_JANA_FILE = Path("Input/Jana Small Finance Bank/AKSHAY JAIN  SOA.pdf")


@pytest.mark.skipif(not _JANA_FILE.exists(), reason="Input/Jana statement not present")
def test_jana_statement_detection_and_extraction() -> None:
    data = _JANA_FILE.read_bytes()
    doc, _, _ = read_pdf(data=data, input_id="jana_test", source_path=_JANA_FILE)

    det = detect_bank_statement(doc)
    assert det.is_bank_statement is True
    assert det.bank_name == "Jana Small finance Bank Limited"
    assert det.matched_profile == "jana_pdf_fmt1"
    assert det.account_identity is not None
    assert det.account_identity.account_holder == "AKSHAY JAIN"
    assert det.account_identity.masked_account_number.endswith("7170")

    cap = BankStatementCapability()
    in_ref = InputRef(
        input_id="in-jana-01",
        source_path=_JANA_FILE,
        display_name=_JANA_FILE.name,
        size_bytes=len(data),
    )
    req = Request(request_id="req-jana-01", requirement="bank_statement", inputs=(in_ref,))
    ctx = ExecutionContext(run_id="run-jana-01", request_id="req-jana-01", trace_id="tr-1", span_id="sp-1")
    res = cap.execute(req, ctx, Result(data=doc))

    consolidation = res.data
    assert consolidation.total_transactions == 87
    assert len(consolidation.statements) == 1

    stmt = consolidation.statements[0]
    assert stmt.bank_name == "Jana Small finance Bank Limited"
    assert stmt.bank_profile == "jana_pdf_fmt1"
    assert stmt.account_identity is not None
    assert stmt.account_identity.account_holder == "AKSHAY JAIN"
    assert stmt.account_identity.masked_account_number.endswith("7170")
    assert stmt.opening_balance == Decimal("0.00")
    assert stmt.closing_balance == Decimal("30.38")
    assert stmt.status == "valid"
    assert len(stmt.issues) == 0

    debits = [t for t in stmt.transactions if t.debit is not None]
    credits = [t for t in stmt.transactions if t.credit is not None]
    assert len(debits) == 49
    assert len(credits) == 38
    assert sum(t.debit for t in debits) == Decimal("984084.00")
    assert sum(t.credit for t in credits) == Decimal("984114.38")

    first_tx = stmt.transactions[0]
    assert first_tx.credit == Decimal("300000.00")
    assert first_tx.running_balance == Decimal("300000.00")
    assert "BANDHAN BANK" in first_tx.description

    last_tx = stmt.transactions[-1]
    assert last_tx.credit == Decimal("10.38")
    assert last_tx.running_balance == Decimal("30.38")
    assert last_tx.description == "NEFT CR-ICIC0000104-ICICI PRUDENTIAL LIFE INSURANCE CO LTD-MR AKSHAY JAIN-ICIN212531977380"
