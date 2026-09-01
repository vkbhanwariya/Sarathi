"""Tests for Axis Bank Statement Profile and Reverse Chronology Handling."""

import csv
from decimal import Decimal
from pathlib import Path
import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, ExecutionProfile, InputRef, Request, Result
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult, ValidationStatus


@pytest.fixture
def axis_reverse_chrono_csv(tmp_path: Path) -> Path:
    """Create realistic Axis Bank CSV fixture with reverse chronological transaction rows."""
    file_path = tmp_path / "axis_statement.csv"
    rows = [
        ["AXIS BANK LTD"],
        ["Account Number : 912010012345678"],
        ["Name : Amit Kumar"],
        [""],
        ["Tran Date", "Value Date", "Transaction Details", "Chq No", "Debit", "Credit", "Balance"],
        ["20-03-2026", "20-03-2026", "DIVIDEND CREDIT", "", "", "5,000.00", "30,000.00"],
        ["10-03-2026", "10-03-2026", "ELECTRICITY BILL", "", "2,000.00", "", "25,000.00"],
        ["01-03-2026", "01-03-2026", "OPENING BALANCE", "", "", "", "27,000.00"],
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return file_path


def test_detect_axis_profile() -> None:
    doc_text = """
    AXIS BANK
    Account Statement
    Account Number : 912010012345678
    Name : Amit Kumar
    """
    doc = CanonicalDocument(document_id="doc-axis-1", text=doc_text)
    ev = detect_bank_statement(doc)
    assert ev.is_bank_statement is True
    assert ev.matched_profile == "axis"
    assert ev.bank_name == "Axis Bank"
    assert ev.account_identity is not None
    assert ev.account_identity.masked_account_number == "XXXXXXXXXXX5678"


def test_e2e_axis_reverse_chronology_consolidation(tmp_path: Path, axis_reverse_chrono_csv: Path) -> None:
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=Darpana(capacity=200),
    )
    req = Request(
        request_id="req-axis-1",
        requirement="bank_statements",
        inputs=(InputRef("i-axis", axis_reverse_chrono_csv, "axis.csv", 100),),
        profile=ExecutionProfile.ACCURATE,
    )
    ctx = ExecutionContext("run-axis-1", "req-axis-1", "t1", "s1")

    res = agni.execute(req, ctx)
    assert isinstance(res, Result)
    assert isinstance(res.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = res.data

    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert stmt.bank_profile == "axis"
    assert stmt.status == ValidationStatus.VALID
    assert len(stmt.transactions) == 2
    assert consolidation.total_debit == Decimal("2000.00")
    assert consolidation.total_credit == Decimal("5000.00")
