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


def test_deduplicate_distinct_documents_without_account_identity() -> None:
    """Transactions with identical fields from distinct unlabelled documents must NOT falsely collide."""
    from sarathi.sankalpa import ProvenanceRecord

    p1 = ProvenanceRecord(source_input_id="doc-A", capability_id="bank_statements", stage="extraction")
    p2 = ProvenanceRecord(source_input_id="doc-B", capability_id="bank_statements", stage="extraction")

    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Cash Withdrawal",
        bank_name="Unknown Bank",
        account_identity=None,
        debit=Decimal("500.00"),
        provenance=(p1,),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Cash Withdrawal",
        bank_name="Unknown Bank",
        account_identity=None,
        debit=Decimal("500.00"),
        provenance=(p2,),
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 2
    assert len(res.duplicates) == 0


def test_deduplicate_merges_provenance_on_drop() -> None:
    """When a duplicate is dropped, its source provenance is merged into the surviving transaction."""
    from sarathi.sankalpa import ProvenanceRecord

    ident = create_account_identity("HDFC Bank", "5010099999")
    p1 = ProvenanceRecord(source_input_id="doc-1", capability_id="bank_statements", stage="extraction", page_number=1)
    p2 = ProvenanceRecord(source_input_id="doc-1", capability_id="bank_statements", stage="extraction", page_number=2)

    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary Credit",
        bank_name="HDFC Bank",
        account_identity=ident,
        credit=Decimal("75000.00"),
        provenance=(p1,),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary Credit",
        bank_name="HDFC Bank",
        account_identity=ident,
        credit=Decimal("75000.00"),
        provenance=(p2,),
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 1
    assert len(res.duplicates) == 1
    surviving = res.unique_transactions[0]
    assert len(surviving.provenance) == 2
    assert p1 in surviving.provenance
    assert p2 in surviving.provenance
