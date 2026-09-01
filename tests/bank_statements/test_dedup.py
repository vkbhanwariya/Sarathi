"""Tests for Transaction Deduplication."""

from datetime import date
from decimal import Decimal

from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.models import (
    DuplicateDecision,
    Transaction,
    create_account_identity,
)


def test_deduplicate_exact_transactions() -> None:
    ident = create_account_identity("State Bank of India", "30123456789")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="UPI Payment",
        bank_name="State Bank of India",
        account_identity=ident,
        debit=Decimal("100.00"),
        running_balance=Decimal("5000.00"),
        reference_number="REF123",
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="UPI Payment",
        bank_name="State Bank of India",
        account_identity=ident,
        debit=Decimal("100.00"),
        running_balance=Decimal("5000.00"),
        reference_number="REF123",
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 1
    assert len(res.duplicates) == 1
    assert res.duplicates[0][2] == DuplicateDecision.PROVEN_DUPLICATE
