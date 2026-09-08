"""Consolidated unit and invariant tests for bank statement deduplication and ordering."""

from __future__ import annotations

import io
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import polars as pl

from sarathi.sankalpa import (
    CanonicalDocument,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    TableData,
)
from sarathi.shakti.bank_statements.capability import BankStatementCapability
from sarathi.shakti.bank_statements.consolidator import (
    build_parquet_artifact,
    consolidate_statements,
)
from sarathi.shakti.bank_statements.deduplicator import deduplicate_transactions
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    DuplicateDecision,
    Transaction,
    ValidationStatus,
    create_account_identity,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


def test_deduplicate_exact_transactions() -> None:
    """Exact match on date, amount, description, ref, and balance drops the duplicate."""
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
    ident = create_account_identity("HDFC Bank", "5010099999")
    p1 = ProvenanceRecord(source_input_id="doc-1", capability_id="bank_statements", stage="extraction", page_number=1)
    p2 = ProvenanceRecord(source_input_id="doc-1", capability_id="bank_statements", stage="extraction", page_number=2)

    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary Credit",
        bank_name="HDFC Bank",
        account_identity=ident,
        reference_number="SAL20260101",
        credit=Decimal("75000.00"),
        provenance=(p1,),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="Salary Credit",
        bank_name="HDFC Bank",
        account_identity=ident,
        reference_number="SAL20260101",
        credit=Decimal("75000.00"),
        provenance=(p2,),
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 1
    assert len(res.duplicates) == 1
    assert res.duplicates[0][2] == DuplicateDecision.PROVEN_DUPLICATE
    surviving = res.unique_transactions[0]
    assert len(surviving.provenance) == 2
    assert p1 in surviving.provenance
    assert p2 in surviving.provenance


def test_deduplicate_probable_retains_both_transactions() -> None:
    """Without reference or running balance, matching date/amount/narration is PROBABLE and retains both."""
    ident = create_account_identity("HDFC Bank", "5010099999")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="ATM Cash Withdrawal",
        bank_name="HDFC Bank",
        account_identity=ident,
        debit=Decimal("5000.00"),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        description="ATM Cash Withdrawal",
        bank_name="HDFC Bank",
        account_identity=ident,
        debit=Decimal("5000.00"),
    )

    res = deduplicate_transactions([tx1, tx2])
    # Both transactions are preserved per Bank Veda
    assert len(res.unique_transactions) == 2
    assert len(res.duplicates) == 1
    assert res.duplicates[0][2] == DuplicateDecision.PROBABLE_DUPLICATE
    # Second transaction receives warning issue
    assert any(iss.code == "PROBABLE_DUPLICATE_TRANSACTION" for iss in res.unique_transactions[1].issues)


def test_deduplicate_contradictory_time_retains_both_transactions() -> None:
    """Transactions with matching date/account/amount/ref but contradictory explicit times must NOT be merged."""
    ident = create_account_identity("HDFC Bank", "5010099999")
    tx1 = Transaction(
        transaction_date=date(2026, 1, 1),
        transaction_time=time(9, 0, 0),
        description="Payment",
        bank_name="HDFC Bank",
        account_identity=ident,
        reference_number="REF123",
        debit=Decimal("100.00"),
        running_balance=Decimal("900.00"),
    )
    tx2 = Transaction(
        transaction_date=date(2026, 1, 1),
        transaction_time=time(11, 0, 0),
        description="Payment",
        bank_name="HDFC Bank",
        account_identity=ident,
        reference_number="REF123",
        debit=Decimal("100.00"),
        running_balance=Decimal("900.00"),
    )

    res = deduplicate_transactions([tx1, tx2])
    assert len(res.unique_transactions) == 2
    assert len(res.duplicates) == 0


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
    """consolidate_statements flattens all valid transactions and sorts chronologically."""
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

    tx_jan3_early = Transaction(
        transaction_date=date(2026, 1, 3),
        transaction_time=time(10, 30),
        description="Jan 3 Early Tx",
        bank_name="SBI",
        debit=Decimal("50.00"),
        sequence_id=1,
        account_identity=ident,
    )
    tx_jan3_late = Transaction(
        transaction_date=date(2026, 1, 3),
        transaction_time=time(15, 45),
        description="Jan 3 Late Tx",
        bank_name="SBI",
        credit=Decimal("300.00"),
        sequence_id=2,
        account_identity=ident,
    )
    stmt2 = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        transactions=(tx_jan3_late, tx_jan3_early),
    )

    res = consolidate_statements([stmt1, stmt2])
    # tx_invalid excluded from valid transactions
    assert len(res.transactions) == 4
    assert res.transactions[0].description == "Jan 2 Tx"
    assert res.transactions[1].description == "Jan 3 Early Tx"
    assert res.transactions[2].description == "Jan 3 Late Tx"
    assert res.transactions[3].description == "Jan 5 Tx"


def test_cross_statement_deduplication_and_exports() -> None:
    """Test that transactions appearing in two overlapping statement files are deduplicated in consolidation and exports."""
    ident = create_account_identity("HDFC Bank", "5010022334455")

    # Common transaction present in both January and February statements
    overlap_tx = Transaction(
        transaction_date=date(2026, 1, 31),
        description="Salary Credit Corp",
        bank_name="HDFC Bank",
        credit=Decimal("50000.00"),
        running_balance=Decimal("65000.00"),
        account_identity=ident,
        sequence_id=10,
    )

    stmt1_tx = Transaction(
        transaction_date=date(2026, 1, 15),
        description="Groceries Store",
        bank_name="HDFC Bank",
        debit=Decimal("2500.00"),
        running_balance=Decimal("15000.00"),
        account_identity=ident,
        sequence_id=5,
    )

    stmt2_tx = Transaction(
        transaction_date=date(2026, 2, 5),
        description="Internet Bill",
        bank_name="HDFC Bank",
        debit=Decimal("1000.00"),
        running_balance=Decimal("64000.00"),
        account_identity=ident,
        sequence_id=1,
    )

    stmt1 = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        transactions=(stmt1_tx, overlap_tx),
        statement_id="stmt_jan",
    )

    stmt2 = BankStatement(
        bank_name="HDFC Bank",
        bank_profile="hdfc",
        account_identity=ident,
        transactions=(overlap_tx, stmt2_tx),
        statement_id="stmt_feb",
    )

    consolidation = consolidate_statements([stmt1, stmt2])

    # 1. Deduplication across statements: 3 unique transactions instead of 4
    assert len(consolidation.transactions) == 3
    assert consolidation.total_transactions == 3
    assert consolidation.total_credit == Decimal("50000.00")
    assert consolidation.total_debit == Decimal("3500.00")

    # Issue recorded for cross-statement duplicate
    dup_issues = [i for i in consolidation.issues if i.code == "CROSS_STATEMENT_DUPLICATE"]
    assert len(dup_issues) == 1

    # 2. Chronological ordering
    assert consolidation.transactions[0].description == "Groceries Store"
    assert consolidation.transactions[1].description == "Salary Credit Corp"
    assert consolidation.transactions[2].description == "Internet Bill"

    # 3. Parquet export strictly reflects canonical sequence
    parquet_art = build_parquet_artifact(consolidation)
    df = pl.read_parquet(io.BytesIO(parquet_art.content))
    assert len(df) == 3
    assert df["description"].to_list() == ["Groceries Store", "Salary Credit Corp", "Internet Bill"]
    assert df["credit"].to_list()[1] == Decimal("50000.00")
