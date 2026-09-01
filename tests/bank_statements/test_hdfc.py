"""Tests for HDFC Bank Statement Profile, Multiline Narrations, and Consolidation."""

import csv
from decimal import Decimal
import io
from pathlib import Path
import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, ExecutionProfile, InputRef, PageData, Request, Result, TableData
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult


@pytest.fixture
def hdfc_statement_csv(tmp_path: Path) -> Path:
    """Create realistic HDFC CSV fixture with multiline narration continuation."""
    file_path = tmp_path / "hdfc_statement.csv"
    rows = [
        ["HDFC BANK LIMITED"],
        ["Account No : 50100234567890"],
        ["Name : Priya Nair"],
        ["Cust ID : 98765432"],
        ["IFSC : HDFC0000123"],
        [""],
        ["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"],
        ["01/01/26", "OPENING BALANCE", "", "01/01/26", "", "", "50,000.00"],
        ["05/01/26", "POS 401234123412 AMAZON INDIA", "REF-99881", "05/01/26", "1,500.00", "", "48,500.00"],
        ["", "E-COMMERCE BANGALORE IN", "", "", "", "", ""],  # Multiline continuation
        ["12/01/26", "NEFT CR-HDFC0000001-TECH CORP SALARY", "N1234567", "12/01/26", "", "100,000.00", "148,500.00"],
        ["31/01/26", "CLOSING BALANCE", "", "31/01/26", "", "", "148,500.00"],
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return file_path


def test_detect_hdfc_profile() -> None:
    doc_text = """
    HDFC BANK
    Account Statement
    Account No : 50100234567890
    Name : Priya Nair
    Cust ID : 98765432
    """
    doc = CanonicalDocument(document_id="doc-hdfc-1", text=doc_text)
    ev = detect_bank_statement(doc)
    assert ev.is_bank_statement is True
    assert ev.matched_profile == "hdfc"
    assert ev.bank_name == "HDFC Bank"
    assert ev.account_identity is not None
    assert ev.account_identity.masked_account_number == "XXXXXXXXXX7890"


def test_e2e_hdfc_multiline_narration_consolidation(tmp_path: Path, hdfc_statement_csv: Path) -> None:
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=Darpana(capacity=200),
    )
    req = Request(
        request_id="req-hdfc-1",
        requirement="bank_statements",
        inputs=(InputRef("i-hdfc", hdfc_statement_csv, "hdfc.csv", 100),),
        profile=ExecutionProfile.ACCURATE,
    )
    ctx = ExecutionContext("run-hdfc-1", "req-hdfc-1", "t1", "s1")

    res = agni.execute(req, ctx)
    assert isinstance(res, Result)
    assert isinstance(res.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = res.data

    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert stmt.bank_profile == "hdfc"
    assert len(stmt.transactions) == 2

    # Check multiline narration merged
    tx1 = stmt.transactions[0]
    assert "POS 401234123412 AMAZON INDIA" in tx1.description
    assert "E-COMMERCE BANGALORE IN" in tx1.description
    assert tx1.debit == Decimal("1500.00")
    assert tx1.running_balance == Decimal("48500.00")

    assert consolidation.total_debit == Decimal("1500.00")
    assert consolidation.total_credit == Decimal("100000.00")
