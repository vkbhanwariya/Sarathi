"""Tests for HDFC Bank Statement Profile with Validated Local Static Fixture."""

from decimal import Decimal
from pathlib import Path

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, ExecutionProfile, InputRef, Request, Result
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.models import BankStatementConsolidationResult

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hdfc_statement.csv"


def test_detect_hdfc_profile() -> None:
    doc_text = _FIXTURE_PATH.read_text(encoding="utf-8")
    doc = CanonicalDocument(document_id="doc-hdfc-fixture", text=doc_text)
    ev = detect_bank_statement(doc)

    assert ev.is_bank_statement is True
    assert ev.matched_profile == "hdfc"
    assert ev.bank_name == "HDFC Bank"
    assert ev.account_identity is not None
    assert ev.account_identity.masked_account_number == "XXXXXXXXXX7890"
    assert ev.account_identity.account_holder == "Priya Nair"


def test_e2e_hdfc_multiline_narration_consolidation(tmp_path: Path) -> None:
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        darpana=Darpana(capacity=200),
    )
    req = Request(
        request_id="req-hdfc-1",
        requirement="bank_statements",
        inputs=(InputRef("i-hdfc", _FIXTURE_PATH, "hdfc_statement.csv", _FIXTURE_PATH.stat().st_size),),
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
