"""Tests for cross-statement deduplication, canonical export sequence, and financial validation."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import polars as pl

from sarathi.shakti.bank_statements.consolidator import (
    build_parquet_artifact,
    consolidate_statements,
)
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationStatus,
    create_account_identity,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


def test_cross_statement_deduplication_and_exports() -> None:
    """Test that transactions appearing in two overlapping statement files are deduplicated in consolidation and exports."""
    ident = create_account_identity("HDFC Bank", "5010022334455")

    # Common transaction present in both January and February statements
    overlap_tx = Transaction(
        transaction_date=date(2026, 1, 31),
        description="Salary Credit Corp",
        bank_name="HDFC Bank",
        credit=Decimal("50000.00"),
        running_balance=Decimal("65000.00"),
        account_identity=ident,
        sequence_id=10,
    )

    stmt1_tx = Transaction(
        transaction_date=date(2026, 1, 15),
        description="Groceries Store",
        bank_name="HDFC Bank",
        debit=Decimal("2500.00"),
        running_balance=Decimal("15000.00"),
        account_identity=ident,
        sequence_id=5,
    )

    stmt2_tx = Transaction(
        transaction_date=date(2026, 2, 5),
        description="Internet Bill",
        bank_name="HDFC Bank",
        debit=Decimal("1000.00"),
        running_balance=Decimal("64000.00"),
        account_identity=ident,
        sequence_id=1,
    )

    stmt1 = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        transactions=(stmt1_tx, overlap_tx),
        statement_id="stmt_jan",
    )

    stmt2 = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        transactions=(overlap_tx, stmt2_tx),
        statement_id="stmt_feb",
    )

    consolidation = consolidate_statements([stmt1, stmt2])

    # 1. Deduplication across statements: 3 unique transactions instead of 4
    assert len(consolidation.transactions) == 3
    assert consolidation.total_transactions == 3
    assert consolidation.total_credit == Decimal("50000.00")
    assert consolidation.total_debit == Decimal("3500.00")

    # Issue recorded for cross-statement duplicate
    dup_issues = [i for i in consolidation.issues if i.code == "CROSS_STATEMENT_DUPLICATE"]
    assert len(dup_issues) == 1

    # 2. Chronological ordering
    assert consolidation.transactions[0].description == "Groceries Store"
    assert consolidation.transactions[1].description == "Salary Credit Corp"
    assert consolidation.transactions[2].description == "Internet Bill"

    # 3. Parquet export strictly reflects canonical sequence
    parquet_art = build_parquet_artifact(consolidation)
    df = pl.read_parquet(io.BytesIO(parquet_art.content))
    assert len(df) == 3
    assert df["description"].to_list() == ["Groceries Store", "Salary Credit Corp", "Internet Bill"]
    assert df["credit"].to_list()[1] == Decimal("50000.00")


def test_totals_exclude_invalid_transactions() -> None:
    """Test that summary metrics strictly exclude INVALID transactions."""
    ident = create_account_identity("SBI", "1234567890")

    tx_valid = Transaction(
        transaction_date=date(2026, 3, 1),
        description="Valid Tx",
        bank_name="SBI",
        debit=Decimal("100.00"),
        account_identity=ident,
    )
    tx_invalid = Transaction(
        transaction_date=date(2026, 3, 2),
        description="Corrupt Tx",
        bank_name="SBI",
        debit=Decimal("9999.00"),
        status=ValidationStatus.INVALID,
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        transactions=(tx_valid, tx_invalid),
    )

    consolidation = consolidate_statements([stmt])
    assert len(consolidation.transactions) == 1
    assert consolidation.total_transactions == 1
    assert consolidation.total_debit == Decimal("100.00")


def test_single_date_transactions_do_not_reverse() -> None:
    """Test that transactions on the same date are not inverted by balance validation."""
    ident = create_account_identity("ICICI Bank", "9876543210")

    tx1 = Transaction(
        transaction_date=date(2026, 4, 10),
        description="Tx One Morning",
        bank_name="ICICI Bank",
        debit=Decimal("50.00"),
        sequence_id=1,
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 4, 10),
        description="Tx Two Afternoon",
        bank_name="ICICI Bank",
        credit=Decimal("100.00"),
        sequence_id=2,
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="ICICI Bank",
        bank_profile="icici",
        account_identity=ident,
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(stmt)
    assert len(validated.transactions) == 2
    # Preserves initial order: tx1 followed by tx2
    assert validated.transactions[0].description == "Tx One Morning"
    assert validated.transactions[1].description == "Tx Two Afternoon"


def test_statement_with_invalid_transactions_becomes_invalid() -> None:
    """Test that a statement containing an INVALID transaction is marked INVALID overall."""
    ident = create_account_identity("Axis Bank", "1122334455")

    tx_valid = Transaction(
        transaction_date=date(2026, 5, 1),
        description="Valid Tx",
        bank_name="Axis Bank",
        credit=Decimal("500.00"),
        account_identity=ident,
    )
    tx_invalid = Transaction(
        transaction_date=date(2026, 5, 2),
        description="Missing Both Debit and Credit",
        bank_name="Axis Bank",
        debit=None,
        credit=None,
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="Axis Bank",
        bank_profile="axis",
        account_identity=ident,
        transactions=(tx_valid, tx_invalid),
    )

    validated = validate_statement_balances(stmt)
    assert validated.status == ValidationStatus.INVALID


def test_validator_preserves_all_statement_fields() -> None:
    """Test that validate_statement_balances preserves statement_id, account_holder, ifsc, etc."""
    ident = create_account_identity("Kotak", "4455667788", account_holder="Alice Smith")

    tx = Transaction(
        transaction_date=date(2026, 6, 1),
        description="Coffee",
        bank_name="Kotak",
        debit=Decimal("200.00"),
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="Kotak",
        bank_profile="kotak",
        account_identity=ident,
        transactions=(tx,),
        statement_id="stmt_custom_id_123",
        account_holder="Alice Smith",
        account_type="Savings",
        branch="MG Road",
        ifsc="KKBK0000123",
        balance_as_on=Decimal("15000.00"),
    )

    validated = validate_statement_balances(stmt)
    assert validated.statement_id == "stmt_custom_id_123"
    assert validated.account_holder == "Alice Smith"
    assert validated.account_type == "Savings"
    assert validated.branch == "MG Road"
    assert validated.ifsc == "KKBK0000123"
    assert validated.balance_as_on == Decimal("15000.00")


def test_cross_account_dedup_isolation() -> None:
    """F11: Transactions with identical details across different accounts are NOT deduplicated."""
    ident_sbi = create_account_identity("SBI", "111122223333")
    ident_hdfc = create_account_identity("HDFC", "999988887777")

    tx_sbi = Transaction(
        transaction_date=date(2026, 4, 1),
        description="Monthly Rent Transfer",
        bank_name="SBI",
        debit=Decimal("25000.00"),
        account_identity=ident_sbi,
        sequence_id=1,
    )
    tx_hdfc = Transaction(
        transaction_date=date(2026, 4, 1),
        description="Monthly Rent Transfer",
        bank_name="HDFC",
        debit=Decimal("25000.00"),
        account_identity=ident_hdfc,
        sequence_id=1,
    )

    stmt_sbi = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident_sbi,
        transactions=(tx_sbi,),
    )
    stmt_hdfc = BankStatement(
        bank_name="HDFC",
        bank_profile="hdfc",
        account_identity=ident_hdfc,
        transactions=(tx_hdfc,),
    )

    res = consolidate_statements([stmt_sbi, stmt_hdfc])
    assert len(res.transactions) == 2
    assert not any(i.code == "CROSS_STATEMENT_DUPLICATE" for i in res.issues)


def test_parquet_artifact_schema_completeness() -> None:
    """F13: Parquet schema includes value_date, posting_date, issues, and metadata."""
    from sarathi.shakti.bank_statements.models import ValidationIssue

    ident = create_account_identity("SBI", "555566667777")
    issue = ValidationIssue(code="TEST_CODE", message="Test issue message", severity="warning")
    tx = Transaction(
        transaction_date=date(2026, 5, 10),
        posting_date=date(2026, 5, 11),
        value_date=date(2026, 5, 12),
        description="Parquet Schema Tx",
        bank_name="SBI",
        credit=Decimal("1234.56"),
        account_identity=ident,
        issues=(issue,),
        metadata={"custom_flag": "audited"},
    )

    stmt = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        transactions=(tx,),
    )

    res = consolidate_statements([stmt])
    payload = build_parquet_artifact(res)

    df = pl.read_parquet(io.BytesIO(payload.content))
    assert "value_date" in df.columns
    assert "posting_date" in df.columns
    assert "issues" in df.columns
    assert "metadata" in df.columns

    assert df["value_date"].to_list() == ["2026-05-12"]
    assert df["posting_date"].to_list() == ["2026-05-11"]
    assert "TEST_CODE" in df["issues"].to_list()[0]
    assert "audited" in df["metadata"].to_list()[0]


def test_eod_and_summary_rows_captured_in_metadata() -> None:
    """F12: EOD_BALANCE and SUMMARY rows are captured in statement.metadata."""
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    cap = BankStatementCapability()
    headers = ("Date", "Narration", "Chq/Ref No", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance")
    row1 = ("01/05/2026", "Salary Credit", "-", "01/05/2026", "", "50000.00", "50000.00")
    row_eod = ("01/05/2026", "EOD Balance", "-", "-", "", "", "50000.00")
    row_summary = ("", "Grand Total", "-", "-", "", "50000.00", "50000.00")

    table = TableData(rows=(headers, row1, row_eod, row_summary))
    doc = CanonicalDocument(
        document_id="doc-eod-summary",
        text="State Bank of India Account 12345678901 Statement",
        source_input_id="in-1",
        tables=(table,),
    )
    req = Request(
        request_id="req-1",
        requirement="bank_statements",
        inputs=(InputRef(input_id="in-1", source_path=Path("test.pdf"), display_name="test.pdf", size_bytes=100),),
    )
    ctx = ExecutionContext(run_id="run-1", request_id="req-1", trace_id="t1", span_id="s1")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmts = res.data.statements
    assert len(stmts) >= 1
    metadata = stmts[0].metadata

    assert "eod_balances" in metadata
    assert len(metadata["eod_balances"]) == 1
    assert metadata["eod_balances"][0]["balance"] == "50000.00"

    assert "summary_rows" in metadata
    assert len(metadata["summary_rows"]) == 1
    assert "Grand Total" in metadata["summary_rows"][0]["raw"]
