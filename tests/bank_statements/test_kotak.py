"""Tests for Kotak Mahindra Bank Statement Profile with Single Amount and Dr/Cr Column."""

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
def kotak_single_amount_csv(tmp_path: Path) -> Path:
    """Create realistic Kotak CSV fixture with single amount column and Dr/Cr indicator."""
    file_path = tmp_path / "kotak_statement.csv"
    rows = [
        ["KOTAK MAHINDRA BANK"],
        ["Account No : 1234567890"],
        ["Account Name : Meera Joshi"],
        ["CRN : 12345678"],
        [""],
        ["Date", "Narration", "Chq / Ref No", "Amount", "Dr / Cr", "Balance"],
        ["01-Apr-2026", "OPENING BALANCE", "", "0.00", "CR", "15,000.00"],
        ["05-Apr-2026", "GROCERY STORE", "REF1122", "3,500.00", "DR", "11,500.00"],
        ["10-Apr-2026", "CONSULTING FEE", "REF3344", "40,000.00", "CR", "51,500.00"],
        ["30-Apr-2026", "CLOSING BALANCE", "", "0.00", "CR", "51,500.00"],
    ]
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return file_path


def test_detect_kotak_profile() -> None:
    doc_text = """
    KOTAK MAHINDRA BANK
    Account Statement
    Account No : 1234567890
    Account Name : Meera Joshi
    """
    doc = CanonicalDocument(document_id="doc-kotak-1", text=doc_text)
    ev = detect_bank_statement(doc)
    assert ev.is_bank_statement is True
    assert ev.matched_profile == "kotak"
    assert ev.bank_name == "Kotak Mahindra Bank"
    assert ev.account_identity is not None
    assert ev.account_identity.masked_account_number == "XXXXXX7890"


def test_e2e_kotak_single_amount_consolidation(tmp_path: Path, kotak_single_amount_csv: Path) -> None:
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=Darpana(capacity=200),
    )
    req = Request(
        request_id="req-kotak-1",
        requirement="bank_statements",
        inputs=(InputRef("i-kotak", kotak_single_amount_csv, "kotak.csv", 100),),
        profile=ExecutionProfile.ACCURATE,
    )
    ctx = ExecutionContext("run-kotak-1", "req-kotak-1", "t1", "s1")

    res = agni.execute(req, ctx)
    assert isinstance(res, Result)
    assert isinstance(res.data, BankStatementConsolidationResult)
    consolidation: BankStatementConsolidationResult = res.data

    assert len(consolidation.statements) == 1
    stmt = consolidation.statements[0]
    assert stmt.bank_profile == "kotak"
    assert len(stmt.transactions) == 2
    assert stmt.transactions[0].debit == Decimal("3500.00")
    assert stmt.transactions[0].credit is None
    assert stmt.transactions[1].credit == Decimal("40000.00")
    assert stmt.transactions[1].debit is None
    assert consolidation.total_debit == Decimal("3500.00")
    assert consolidation.total_credit == Decimal("40000.00")
