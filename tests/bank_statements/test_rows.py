"""Tests for Raw Row Classification."""

from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row


def test_classify_transaction_row() -> None:
    row = ["01/01/2026", "UPI-1234-Merchant", "UPI1234", "100.00", "", "5000.00"]
    assert classify_row(row, date_col_idx=0) == RowType.TRANSACTION


def test_classify_opening_balance_row() -> None:
    row = ["01/01/2026", "OPENING BALANCE", "", "", "", "5100.00"]
    assert classify_row(row) == RowType.OPENING_BALANCE


def test_classify_closing_balance_row() -> None:
    row = ["31/01/2026", "CLOSING BALANCE B/F", "", "", "", "10500.00"]
    assert classify_row(row) == RowType.CLOSING_BALANCE


def test_classify_noise_and_summary_row() -> None:
    assert classify_row(["", "", "", ""]) == RowType.NOISE
    assert classify_row(["Total Debits / Credits", "1000.00", "5000.00"]) == RowType.SUMMARY


def test_classify_row_with_financial_figures_but_no_date() -> None:
    """Rows with financial figures but no date must be classified as TRANSACTION, not CONTINUATION."""
    row = ["", "Second Transfer Same Day", "REF999", "250.00", "", "4750.00"]
    # With explicit amount col indices
    assert classify_row(row, date_col_idx=0, amount_col_indices=[3, 4, 5]) == RowType.TRANSACTION
    # With fallback monetary inspection
    assert classify_row(row, date_col_idx=0) == RowType.TRANSACTION


def test_classify_row_pure_continuation() -> None:
    """Rows with text but no financial figures are classified as CONTINUATION."""
    row = ["", "Extended details of prior transaction with no amounts", "", "", "", ""]
    assert classify_row(row, date_col_idx=0, amount_col_indices=[3, 4, 5]) == RowType.CONTINUATION


def test_date_inheritance_resolution_in_capability() -> None:
    """A row with financial figures but no date inherits date from previous transaction and stays distinct."""
    from datetime import date
    from decimal import Decimal
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability
    from sarathi.shakti.bank_statements.models import BankStatement

    headers = ("Date", "Description", "Debit", "Credit", "Balance")
    row1 = ("01/01/2026", "First Tx", "100.00", "", "5000.00")
    row2 = ("", "Second Tx No Date", "200.00", "", "4800.00")
    row3 = ("", "Narration for second tx", "", "", "")

    table = TableData(rows=(headers, row1, row2, row3))
    doc = CanonicalDocument(
        document_id="doc-date-inherit",
        text="Bank Statement\nAccount Number: 1234567890",
        tables=(table,),
    )
    req = Request(
        request_id="req-date-inherit",
        requirement="bank_statements",
        inputs=(InputRef("i1", Path("test.csv"), "test.csv", 100),),
    )
    ctx = ExecutionContext("run-1", "req-date-inherit", "t1", "s1")
    cap = BankStatementCapability()
    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    stmt: BankStatement = res.data.statements[0]

    assert len(stmt.transactions) == 2
    tx1, tx2 = stmt.transactions[0], stmt.transactions[1]
    assert tx1.transaction_date == date(2026, 1, 1)
    assert tx1.description == "First Tx"
    assert tx1.debit == Decimal("100.00")

    # Inherited date from previous transaction, narration kept separate
    assert tx2.transaction_date == date(2026, 1, 1)
    assert "Second Tx No Date" in tx2.description
    assert "Narration for second tx" in tx2.description
    assert tx2.debit == Decimal("200.00")
