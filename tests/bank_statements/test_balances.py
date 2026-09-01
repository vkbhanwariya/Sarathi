"""Tests for Running Balance Continuity and Reconciliation."""

from datetime import date
from decimal import Decimal
import pytest

from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationStatus,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


def test_valid_running_balance_continuity() -> None:
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary Deposit",
        bank_name="State Bank of India",
        credit=Decimal("50000.00"),
        running_balance=Decimal("60000.00"),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Electricity Bill",
        bank_name="State Bank of India",
        debit=Decimal("2500.00"),
        running_balance=Decimal("57500.00"),
    )

    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_number="30123456789",
        account_holder="Rahul Sharma",
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("57500.00"),
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.VALID
    assert len(validated.issues) == 0


def test_running_balance_discontinuity_detected() -> None:
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("5000.00"),  # Expected 10000 + 1000 = 11000
    )

    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_number="30123456789",
        account_holder="Rahul Sharma",
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("5000.00"),
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "BALANCE_DISCONTINUITY" for i in validated.transactions[0].issues)


def test_statement_reconciliation_failure_detected() -> None:
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Deposit",
        bank_name="State Bank of India",
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
    )

    statement = BankStatement(
        bank_name="State Bank of India",
        bank_profile="sbi",
        account_number="30123456789",
        account_holder="Rahul Sharma",
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("20000.00"),  # Expected 11000, mismatch!
        transactions=(tx1,),
    )

    validated = validate_statement_balances(statement)
    assert validated.status == ValidationStatus.WARNING
    assert any(i.code == "RECONCILIATION_FAILED" for i in validated.issues)
