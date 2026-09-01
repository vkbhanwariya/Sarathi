"""Tests for ICICI Bank Statement Profile and Consolidation."""

import csv
from decimal import Decimal
from pathlib import Path
import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, ExecutionProfile, InputRef, Request, Result
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult


@pytest.fixture
def icici_statement_csv(tmp_path: Path) -> Path:
    """Create realistic ICICI Bank CSV fixture."""
    file_path = tmp_path / "icici_statement.csv"
    rows = [
        ["ICICI BANK LIMITED"],
        ["Account Number : 123456789012"],
        ["Account Name : Anita Patel"],
        ["IFSC : ICIC0000002"],
        [""],
        ["Transaction Date", "Value Date", "Cheque Number", "Transaction Remarks", "Withdrawal Amount (INR )", "Deposit Amount (INR )", "Balance (INR )"],
        ["01-02-2026", "01-02-2026", "", "OPENING BALANCE", "", "", "75,000.00"],
        ["03-02-2026", "03-02-2026", "CHQ551", "CHEQUE CLG", "25,000.00", "", "50,000.00"],
        ["15-02-2026", "15-02-2026", "", "INT.PD", "", "750.00", "50,750.00"],
        ["28-02-2026", "28-02-2026", "", "CLOSING BALANCE", "", "", "50,750.00"],
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return file_path


def test_detect_icici_profile() -> None:
    doc_text = """
    ICICI BANK
    Account Statement
    Account Number : 123456789012
    Account Name : Anita Patel
    """
    doc = CanonicalDocument(document_id="doc-icici-1", text=doc_text)
    ev = detect_bank_statement(doc)
    assert ev.is_bank_statement is True
    assert ev.matched_profile == "icici"
    assert ev.bank_name == "ICICI Bank"
    assert ev.account_identity is not None
    assert ev.account_identity.masked_account_number == "XXXXXXXX9012"


def test_e2e_icici_consolidation(tmp_path: Path, icici_statement_csv: Path) -> None:
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=Darpana(capacity=200),
    )
    req = Request(
        request_id="req-icici-1",
        requirement="bank_statements",
        inputs=(InputRef("i-icici", icici_statement_csv, "icici.csv", 100),),
        profile=ExecutionProfile.ACCURATE,
    )
    ctx = ExecutionContext("run-icici-1", "req-icici-1", "t1", "s1")

    res = agni.execute(req, ctx)
    assert isinstance(res, Result)
    assert isinstance(res.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = res.data

    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert stmt.bank_profile == "icici"
    assert len(stmt.transactions) == 2
    assert consolidation.total_debit == Decimal("25000.00")
    assert consolidation.total_credit == Decimal("750.00")
