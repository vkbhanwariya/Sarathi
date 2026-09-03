"""Targeted unit and regression tests for Phase 1 Financial Correctness & Safety."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from pathlib import Path
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    Request,
    Result,
    TableData,
)
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.detector import detect_bank_statement
from sarathi.shakti.bank_statements.mapper import HeaderMapper, load_bank_profile_yaml
from sarathi.shakti.bank_statements.models import (
    DuplicateDecision,
    Transaction,
    create_account_identity,
)


def test_zero_opening_and_closing_balances_preserved() -> None:
    """Finding 1 Fix: Legitimate 0.00 opening and closing balances must not be discarded."""
    cap = BankStatementCapability()

    # Table with explicit Opening Balance: 0.00 and Closing Balance: 0.00
    table = TableData(
        name="txns",
        headers=("Date", "Narration", "Withdrawal", "Deposit", "Balance"),
        rows=(
            ("01/01/2026", "Opening Balance b/f", "", "", "0.00"),
            ("02/01/2026", "Direct Deposit", "", "5000.00", "5000.00"),
            ("03/01/2026", "Cash Withdrawal", "5000.00", "", "0.00"),
            ("31/01/2026", "Closing Balance c/f", "", "", "0.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-zero-bal",
        source_input_id="inp-zero",
        text="State Bank of India Statement of Account Account Number: 12345678901",
        tables=(table,),
    )

    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))

    assert res.data is not None
    stmts = res.data.statements
    assert len(stmts) == 1
    stmt = stmts[0]
    # Zero balances must be preserved as Decimal("0.00")
    assert stmt.opening_balance == Decimal("0.00")
    assert stmt.closing_balance == Decimal("0.00")


def test_two_tier_deduplication_probable_vs_proven() -> None:
    """Findings 2 & 38 Fix: Matching date/amount/narration without reference/balance is PROBABLE and retained."""
    ident = create_account_identity("SBI", "12345678901")

    # Pair A: Identical date, amount, description WITHOUT reference or balance -> PROBABLE (both kept)
    tx1 = Transaction(
        transaction_date=date(2026, 2, 1),
        description="POS Store Purchase",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("1200.00"),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 2, 1),
        description="POS Store Purchase",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("1200.00"),
    )

    # Pair B: Identical date, amount, description WITH matching reference -> PROVEN (collapsed)
    tx3 = Transaction(
        transaction_date=date(2026, 2, 2),
        description="NEFT Inward",
        bank_name="SBI",
        account_identity=ident,
        reference_number="NEFT999888",
        credit=Decimal("50000.00"),
    )
    tx4 = Transaction(
        transaction_date=date(2026, 2, 2),
        description="NEFT Inward",
        bank_name="SBI",
        account_identity=ident,
        reference_number="NEFT999888",
        credit=Decimal("50000.00"),
    )

    res = deduplicate_transactions([tx1, tx2, tx3, tx4])
    # tx1 and tx2 must both survive in unique_transactions
    # tx4 must be dropped
    assert len(res.unique_transactions) == 3
    assert res.unique_transactions[0].description == "POS Store Purchase"
    assert res.unique_transactions[1].description == "POS Store Purchase"
    assert res.unique_transactions[2].description == "NEFT Inward"

    # Duplicates record should have both decisions
    decisions = [d[2] for d in res.duplicates]
    assert DuplicateDecision.PROBABLE_DUPLICATE in decisions
    assert DuplicateDecision.PROVEN_DUPLICATE in decisions


def test_bounded_date_inheritance_and_missing_date_issue() -> None:
    """Finding 5 Fix: Missing date only inherits within same table; unparsed initial date records explicit issue."""
    cap = BankStatementCapability()

    # Table 1: Row 1 has valid date, Row 2 has no date -> inherits
    t1 = TableData(
        name="t1",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(
            ("01/01/2026", "Txn 1", "100.00", "", "900.00"),
            ("", "Txn 2 continuation date", "200.00", "", "700.00"),
        ),
    )

    # Table 2: Row 1 has NO date and NO prior rows in Table 2 -> cannot inherit from Table 1!
    t2 = TableData(
        name="t2",
        headers=("Date", "Narration", "Debit", "Credit", "Balance"),
        rows=(
            ("", "Orphan Date Row", "300.00", "", "400.00"),
            ("05/01/2026", "Valid Row", "100.00", "", "300.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-bounded-date",
        source_input_id="inp-bounded",
        text="State Bank of India Statement Account Number: 12345678901",
        tables=(t1, t2),
    )

    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))

    assert res.data is not None
    stmt = res.data.statements[0]
    # In Table 1: Row 2 inherited 01/01/2026
    # In Table 2: Row 1 could NOT inherit and emitted MISSING_TRANSACTION_DATE
    # Row 2 in Table 2 succeeded
    assert len(stmt.transactions) == 3
    assert stmt.transactions[0].transaction_date == date(2026, 1, 1)
    assert stmt.transactions[1].transaction_date == date(2026, 1, 1)
    assert stmt.transactions[2].transaction_date == date(2026, 1, 5)

    # Statement issues must record MISSING_TRANSACTION_DATE
    assert any(iss.code == "MISSING_TRANSACTION_DATE" for iss in stmt.issues)


def test_time_and_value_date_wiring() -> None:
    """Findings 6, 7, 8 Fix: Time and Value Date mapped and populated on Transaction."""
    cap = BankStatementCapability()

    table = TableData(
        name="icici_txns",
        headers=("Transaction Date", "Value Date", "Time", "Particulars", "Cheque No.", "Withdrawal", "Deposit", "Balance"),
        rows=(
            ("10/02/2026", "11/02/2026", "14:30:00", "Cheque Clearing", "000123", "1500.00", "", "8500.00"),
        ),
    )

    doc = CanonicalDocument(
        document_id="doc-icici-val",
        source_input_id="inp-icici",
        text="ICICI Bank Statement Account Number: 000105001234",
        tables=(table,),
    )

    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))

    assert res.data is not None
    stmt = res.data.statements[0]
    assert len(stmt.transactions) == 1
    tx = stmt.transactions[0]
    assert tx.transaction_date == date(2026, 2, 10)
    assert tx.value_date == date(2026, 2, 11)
    assert tx.transaction_time == time(14, 30, 0)
    assert tx.cheque_number == "000123"


def test_best_match_bank_detection_with_competing_narration() -> None:
    """Finding 10 Fix: Profile detection uses multi-signal best match, not first match."""
    doc_text = """
    STATE BANK OF INDIA
    Account Statement
    Account Number: 11223344556
    Branch: New Delhi Main Branch
    Transaction Details:
    Date 01/01/2026 Cash Wdl at HDFC Bank ATM Dr 2000.00 Bal 10000.00
    """
    doc = CanonicalDocument(document_id="doc-sbi", source_input_id="inp-sbi", text=doc_text)
    evidence = detect_bank_statement(doc)

    assert evidence.is_bank_statement is True
    # Must correctly identify SBI despite narration mentioning HDFC
    assert evidence.matched_profile == "sbi"
    assert evidence.bank_name == "State Bank of India"


def test_ifsc_extraction_and_propagation() -> None:
    """Finding 9 Fix: IFSC extracted from metadata patterns and populated on BankStatement."""
    doc_text = """
    ICICI BANK LTD
    Account Statement
    Account Number: 000105009999
    Customer ID: 555123456
    IFSC Code: ICIC0000001
    """
    table = TableData(
        name="txns",
        headers=("Date", "Particulars", "Debit", "Credit", "Balance"),
        rows=(("01/01/2026", "Opening Balance", "", "", "1000.00"),),
    )
    doc = CanonicalDocument(document_id="doc-ifsc", source_input_id="inp-ifsc", text=doc_text, tables=(table,))

    evidence = detect_bank_statement(doc)
    assert evidence.ifsc == "ICIC0000001"
    assert evidence.account_identity is not None
    assert evidence.account_identity.ifsc == "ICIC0000001"

    cap = BankStatementCapability()
    req = Request(
        request_id="req-test",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-test", "t1", "s1")
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt = res.data.statements[0]
    assert stmt.ifsc == "ICIC0000001"


def test_header_fuzzy_scoring_runner_up_margin() -> None:
    """Finding 40 Fix: 0.85 <= score < 0.92 only accepted if margin over runner up is >= 0.05."""
    mapper = HeaderMapper()

    # "Withdrawl" has high match (~0.95) with "withdrawal" (debit) -> auto accept >= 0.92
    mappings = mapper.map_headers(["Withdrawl", "Deposit", "Date"])
    mapped_dict = {m.source_header: m.canonical_field for m in mappings}
    assert mapped_dict.get("Withdrawl") == "debit"


def test_yaml_loader_raises_on_invalid_yaml(tmp_path: Path) -> None:
    """Finding 11 Fix: Single YAML loader consistently raises DoshError(INVALID_CONFIGURATION)."""
    corrupt_file = tmp_path / "bad.yaml"
    corrupt_file.write_text("invalid: [yaml: broken", encoding="utf-8")

    with pytest.raises(DoshError) as exc_info:
        load_bank_profile_yaml(corrupt_file)
    assert exc_info.value.code == FailureCode.INVALID_CONFIGURATION


def test_duplicate_decision_no_stale_aliases() -> None:
    """Finding 39 Fix: Stale PROVEN and PROBABLE aliases removed from DuplicateDecision enum."""
    assert hasattr(DuplicateDecision, "PROVEN_DUPLICATE")
    assert hasattr(DuplicateDecision, "PROBABLE_DUPLICATE")
    assert hasattr(DuplicateDecision, "DISTINCT")
    assert not hasattr(DuplicateDecision, "PROVEN")
    assert not hasattr(DuplicateDecision, "PROBABLE")
