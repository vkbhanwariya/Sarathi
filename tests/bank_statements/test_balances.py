"""Tests for Bank Statement Balances, Invariants, and Reconciliation."""

from datetime import date
from decimal import Decimal
import pytest

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
