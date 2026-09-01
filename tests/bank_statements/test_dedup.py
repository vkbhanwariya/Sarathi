"""Tests for Transaction Deduplication."""

from datetime import date
from decimal import Decimal
import pytest

from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.models import DuplicateDecision, Transaction


def test_deduplicate_exact_transactions() -> None:
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="UPI Payment",
        bank_name="State Bank of India",
        account_number="30123456789",
        debit=Decimal("100.00"),
        running_balance=Decimal("5000.00"),
        reference_number="REF123",
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="UPI Payment",
        bank_name="State Bank of India",
        account_number="30123456789",
        debit=Decimal("100.00"),
        running_balance=Decimal("5000.00"),
        reference_number="REF123",
    )
    tx3 = Transaction(
        transaction_date=date(2026, 1, 2),
        description="ATM Withdrawal",
        bank_name="State Bank of India",
        account_number="30123456789",
        debit=Decimal("500.00"),
        running_balance=Decimal("4500.00"),
        reference_number="ATM999",
    )

    res = deduplicate_transactions([tx1, tx2, tx3])
    assert len(res.unique_transactions) == 2
    assert len(res.duplicates) == 1
    assert res.duplicates[0][2] == DuplicateDecision.PROVEN_DUPLICATE
