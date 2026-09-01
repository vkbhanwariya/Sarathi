"""Tests for Overlapping Statement Period Deduplication and Sparse Balances."""

from datetime import date
from decimal import Decimal

from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    DuplicateDecision,
    Transaction,
    create_account_identity,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


def test_overlapping_statement_period_deduplication() -> None:
    """Verify transactions present in overlapping statement ranges are deduplicated cleanly."""
    ident = create_account_identity("State Bank of India", "30123456789")

    # Statement 1 transactions (Jan 1 to Jan 20)
    tx1 = Transaction(
        transaction_date=date(2026, 1, 5),
        description="Electricity Bill",
        bank_name="State Bank of India",
        debit=Decimal("1200.00"),
        running_balance=Decimal("8800.00"),
        reference_number="TXN1001",
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 15),
        description="Salary Credit",
        bank_name="State Bank of India",
        credit=Decimal("50000.00"),
        running_balance=Decimal("58800.00"),
        reference_number="SAL2026",
        account_identity=ident,
    )

    # Statement 2 transactions (Jan 10 to Jan 31) overlapping tx2 and adding tx3
    tx2_overlap = Transaction(
        transaction_date=date(2026, 1, 15),
        description="Salary Credit",
        bank_name="State Bank of India",
        credit=Decimal("50000.00"),
        running_balance=Decimal("58800.00"),
        reference_number="SAL2026",
        account_identity=ident,
    )
    tx3 = Transaction(
        transaction_date=date(2026, 1, 25),
        description="Grocery Store",
        bank_name="State Bank of India",
        debit=Decimal("2500.00"),
        running_balance=Decimal("56300.00"),
        reference_number="POS9911",
        account_identity=ident,
    )

    all_txns = [tx1, tx2, tx2_overlap, tx3]
    res = deduplicate_transactions(all_txns)

    assert len(res.unique_transactions) == 3
    assert len(res.duplicates) == 1
    dup = res.duplicates[0]
    assert dup[2] == DuplicateDecision.PROVEN_DUPLICATE
    assert dup[1].reference_number == "SAL2026"


def test_sparse_balance_continuity_derivation() -> None:
    """Verify sparse running balance rows (balance is None) continuity."""
    ident = create_account_identity("HDFC Bank", "50100234567890")

    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Opening",
        bank_name="HDFC Bank",
        credit=Decimal("1000.00"),
        running_balance=Decimal("11000.00"),
        account_identity=ident,
    )
    # tx2 has no explicit balance in raw statement
    tx2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Withdrawal without explicit balance",
        bank_name="HDFC Bank",
        debit=Decimal("2000.00"),
        running_balance=None,
        account_identity=ident,
    )
    # tx3 has explicit balance which matches derived 11000 - 2000 + 500 = 9500
    tx3 = Transaction(
        transaction_date=date(2026, 1, 3),
        description="Deposit",
        bank_name="HDFC Bank",
        credit=Decimal("500.00"),
        running_balance=Decimal("9500.00"),
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("9500.00"),
        transactions=(tx1, tx2, tx3),
    )

    validated = validate_statement_balances(stmt)
    assert len(validated.issues) == 0
    assert validated.status.value == "valid"
