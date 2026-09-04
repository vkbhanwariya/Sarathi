"""Unit tests for continuous sequence ordering and strong-signal deduplication in bank statements."""

from datetime import date
from decimal import Decimal

from sarathi.sankalpa import CanonicalDocument, PageData, TableData
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.models import (
    DuplicateDecision,
    Transaction,
    create_account_identity,
)


def test_continuous_monotonic_sequence_id_across_tables() -> None:
    """Verify sequence_id increments monotonically across multiple tables/pages instead of resetting."""
    cap = BankStatementCapability()

    table1 = TableData(
        headers=("Date", "Description", "Debit", "Credit", "Balance"),
        rows=(
            ("01/01/2026", "Tx 1 Page 1", "100.00", "", "1000.00"),
            ("02/01/2026", "Tx 2 Page 1", "200.00", "", "800.00"),
        ),
    )
    table2 = TableData(
        headers=("Date", "Description", "Debit", "Credit", "Balance"),
        rows=(
            ("03/01/2026", "Tx 3 Page 2", "300.00", "", "500.00"),
            ("04/01/2026", "Tx 4 Page 2", "50.00", "", "450.00"),
        ),
    )

    page1 = PageData(page_number=1, tables=(table1,))
    page2 = PageData(page_number=2, tables=(table2,))

    doc = CanonicalDocument(
        document_id="doc_multi_page",
        source_input_id="bank_doc_multi_page",
        pages=(page1, page2),
    )

    from pathlib import Path

    from sarathi.sankalpa import InputRef, Request

    req = Request(
        request_id="req-1",
        requirement="bank_statements",
        inputs=(InputRef(input_id="in-1", source_path=Path("test.pdf"), display_name="test.pdf", size_bytes=100),),
    )
    raw_txns, _, _, _ = cap._extract_table_data(doc, req, "sbi", "State Bank of India", None)
    assert len(raw_txns) == 4
    # sequence_ids must be 1, 2, 3, 4 strictly monotonic
    seq_ids = [tx.sequence_id for tx in raw_txns]
    assert seq_ids == [1, 2, 3, 4]


def test_dedup_strong_signal_running_balance_without_reference() -> None:
    """Transactions with matching running balance and no contradictions are PROVEN_DUPLICATE."""
    ident = create_account_identity("SBI", "12345678901")
    tx1 = Transaction(
        transaction_date=date(2026, 3, 1),
        description="Electricity Bill",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("1500.00"),
        running_balance=Decimal("25000.00"),
        sequence_id=10,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 3, 1),
        description="Electricity Bill",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("1500.00"),
        running_balance=Decimal("25000.00"),
        reference_number="REF-ELEC-99",  # tx2 has reference, tx1 lacks it
        sequence_id=25,
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 1
    assert len(res.duplicates) == 1
    assert res.duplicates[0][2] == DuplicateDecision.PROVEN_DUPLICATE
    surviving = res.unique_transactions[0]
    # Sequence id of original surviving transaction preserved
    assert surviving.sequence_id == 10
    # Reference number enriched from tx2
    assert surviving.reference_number == "REF-ELEC-99"


def test_dedup_contradictory_running_balance_rejected() -> None:
    """Transactions with identical date, amount, narration but conflicting running balance are DISTINCT."""
    ident = create_account_identity("SBI", "12345678901")
    tx1 = Transaction(
        transaction_date=date(2026, 3, 1),
        description="ATM Cash Withdrawal",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("2000.00"),
        running_balance=Decimal("18000.00"),
        sequence_id=1,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 3, 1),
        description="ATM Cash Withdrawal",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("2000.00"),
        running_balance=Decimal("16000.00"),
        sequence_id=2,
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 2
    assert len(res.duplicates) == 0


def test_dedup_contradictory_reference_number_rejected() -> None:
    """Transactions with identical date, amount, narration but conflicting references are DISTINCT."""
    ident = create_account_identity("SBI", "12345678901")
    tx1 = Transaction(
        transaction_date=date(2026, 3, 1),
        description="UPI Payment",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("500.00"),
        reference_number="UPI-0001",
        sequence_id=1,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 3, 1),
        description="UPI Payment",
        bank_name="SBI",
        account_identity=ident,
        debit=Decimal("500.00"),
        reference_number="UPI-0002",
        sequence_id=2,
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 2
    assert len(res.duplicates) == 0
