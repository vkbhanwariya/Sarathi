"""Tests for Bank Statement Balances, Invariants, and Reconciliation."""

from datetime import date
from decimal import Decimal

from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationStatus,
    create_account_identity,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


def test_valid_running_balance_continuity() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Withdrawal",
        bank_name="State Bank of India",
        debit=Decimal("500.00"),
        running_balance=Decimal("10500.00"),
        account_identity=ident,
    )
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("10500.00"),
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.VALID
    assert len(validated.issues) == 0


def test_running_balance_discontinuity_detected() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("5000.00"),  # Expected 10000 + 1000 = 11000
        account_identity=ident,
    )
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("5000.00"),
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "RUNNING_BALANCE_DISCONTINUITY" for i in validated.issues)


def test_statement_reconciliation_failure_detected() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("20000.00"),  # Expected 11000, mismatch!
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "RECONCILIATION_MISMATCH" for i in validated.issues)


def test_missing_opening_balance_inferred_from_closing_and_txns() -> None:
    ident = create_account_identity("HDFC Bank", "501001234567")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary",
        bank_name="HDFC Bank",
        credit=Decimal("50000.00"),
        running_balance=Decimal("75000.00"),
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Rent",
        bank_name="HDFC Bank",
        debit=Decimal("15000.00"),
        running_balance=Decimal("60000.00"),
        account_identity=ident,
    )
    # opening_balance missing from scanned header card
    statement = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        opening_balance=None,
        closing_balance=Decimal("60000.00"),
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.VALID
    assert validated.opening_balance == Decimal("25000.00")
    assert validated.closing_balance == Decimal("60000.00")
    assert len(validated.issues) == 0


def test_bidirectional_isolated_header_discontinuity_detection() -> None:
    ident = create_account_identity("ICICI Bank", "0011223344")
    # Row 1 and 2 are consistent with closing balance 15000
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="ICICI Bank",
        credit=Decimal("5000.00"),
        running_balance=Decimal("15000.00"),
        account_identity=ident,
    )
    # Header opening balance was OCR misread as 5000 instead of 10000
    statement = BankStatement(
        bank_name="ICICI Bank",
        bank_profile="icici",
        account_identity=ident,
        opening_balance=Decimal("5000.00"),
        closing_balance=Decimal("15000.00"),
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    disc_issue = next(i for i in validated.issues if i.code == "RUNNING_BALANCE_DISCONTINUITY")
    assert disc_issue.context is not None
    assert disc_issue.context.get("isolated_upstream_discontinuity") == "true"
    assert disc_issue.context.get("suspected_source") == "header_opening_balance_ocr"


def test_zero_opening_and_closing_balances_preserved() -> None:
    """Legitimate 0.00 opening and closing balances must not be discarded."""
    from pathlib import Path

    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result, TableData
    from sarathi.shakti.bank_statements.capability import BankStatementCapability

    cap = BankStatementCapability()
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
    assert stmt.opening_balance == Decimal("0.00")
    assert stmt.closing_balance == Decimal("0.00")


def test_debit_credit_inversion_detected_and_healed() -> None:
    """Proves validate_statement_balances detects swapped debit/credit columns and restores continuity."""
    ident = create_account_identity("State Bank of India", "30123456789")
    # Columns were inverted: Deposits entered in debit, withdrawals entered in credit
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Client Remittance (Inverted to Debit)",
        bank_name="State Bank of India",
        debit=Decimal("2000.00"),
        credit=None,
        running_balance=Decimal("12000.00"),
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Office Expense (Inverted to Credit)",
        bank_name="State Bank of India",
        debit=None,
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    tx3 = Transaction(
        transaction_date=date(2026, 1, 3),
        description="Customer Invoice Payment (Inverted to Debit)",
        bank_name="State Bank of India",
        debit=Decimal("5000.00"),
        credit=None,
        running_balance=Decimal("16000.00"),
        account_identity=ident,
    )

    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("16000.00"),
        transactions=(tx1, tx2, tx3),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "DEBIT_CREDIT_INVERSION_DETECTED" for i in validated.issues)
    assert not any(i.code == "RUNNING_BALANCE_DISCONTINUITY" for i in validated.issues)
    assert not any(i.code == "RECONCILIATION_MISMATCH" for i in validated.issues)

    # Verify that debits and credits were successfully swapped
    txns = validated.transactions
    assert txns[0].credit == Decimal("2000.00") and txns[0].debit is None
    assert txns[1].debit == Decimal("1000.00") and txns[1].credit is None
    assert txns[2].credit == Decimal("5000.00") and txns[2].debit is None
