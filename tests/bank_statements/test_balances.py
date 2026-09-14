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
