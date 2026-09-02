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


def test_consolidate_statements_flattens_and_sorts_chronologically() -> None:
    """consolidate_statements flattens all valid transactions and sorts by (transaction_date, posting_date, sequence_id)."""
    from sarathi.shakti.bank_statements.consolidator import consolidate_statements
    from sarathi.shakti.bank_statements.models import ValidationStatus

    ident = create_account_identity("SBI", "111122223333")

    tx_invalid = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Invalid Missing Amounts",
        bank_name="SBI",
        account_identity=ident,
        status=ValidationStatus.INVALID,
    )
    tx_jan2 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="Jan 2 Tx",
        bank_name="SBI",
        debit=Decimal("100.00"),
        sequence_id=1,
        account_identity=ident,
    )
    tx_jan5 = Transaction(
        transaction_date=date(2026, 1, 5),
        description="Jan 5 Tx",
        bank_name="SBI",
        credit=Decimal("500.00"),
        sequence_id=2,
        account_identity=ident,
    )
    stmt1 = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        transactions=(tx_jan5, tx_jan2, tx_invalid),
    )

    tx_jan3_late_post = Transaction(
        transaction_date=date(2026, 1, 3),
        posting_date=date(2026, 1, 4),
        description="Jan 3 Late Posting",
        bank_name="SBI",
        debit=Decimal("50.00"),
        sequence_id=1,
        account_identity=ident,
    )
    tx_jan3_same_post = Transaction(
        transaction_date=date(2026, 1, 3),
        posting_date=date(2026, 1, 3),
        description="Jan 3 Same Day Posting",
        bank_name="SBI",
        credit=Decimal("300.00"),
        sequence_id=2,
        account_identity=ident,
    )
    stmt2 = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        transactions=(tx_jan3_late_post, tx_jan3_same_post),
    )

    res = consolidate_statements([stmt1, stmt2])
    # tx_invalid excluded from valid transactions
    assert len(res.transactions) == 4
    assert res.transactions[0].description == "Jan 2 Tx"
    assert res.transactions[1].description == "Jan 3 Same Day Posting"
    assert res.transactions[2].description == "Jan 3 Late Posting"
    assert res.transactions[3].description == "Jan 5 Tx"
