"""Tests for cross-statement deduplication, canonical export sequence, and financial validation."""

from __future__ import annotations

import io
from datetime import date, time
from decimal import Decimal

import polars as pl
import pytest

from sarathi.shakti.bank_statements.consolidator import (
    build_parquet_artifact,
    build_xlsx_artifact,
    consolidate_statements,
)
from sarathi.shakti.bank_statements.models import (
    BankStatement,
    Transaction,
    ValidationStatus,
    create_account_identity,
)
from sarathi.shakti.bank_statements.validator import validate_statement_balances


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


def test_totals_exclude_invalid_transactions() -> None:
    """Test that summary metrics strictly exclude INVALID transactions."""
    ident = create_account_identity("SBI", "1234567890")

    tx_valid = Transaction(
        transaction_date=date(2026, 3, 1),
        description="Valid Tx",
        bank_name="SBI",
        debit=Decimal("100.00"),
        account_identity=ident,
    )
    tx_invalid = Transaction(
        transaction_date=date(2026, 3, 2),
        description="Corrupt Tx",
        bank_name="SBI",
        debit=Decimal("9999.00"),
        status=ValidationStatus.INVALID,
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="SBI",
        bank_profile="sbi",
        account_identity=ident,
        transactions=(tx_valid, tx_invalid),
    )

    consolidation = consolidate_statements([stmt])
    assert len(consolidation.transactions) == 1
    assert consolidation.total_transactions == 1
    assert consolidation.total_debit == Decimal("100.00")


def test_single_date_transactions_do_not_reverse() -> None:
    """Test that transactions on the same date are not inverted by balance validation."""
    ident = create_account_identity("ICICI Bank", "9876543210")

    tx1 = Transaction(
        transaction_date=date(2026, 4, 10),
        description="Tx One Morning",
        bank_name="ICICI Bank",
        debit=Decimal("50.00"),
        sequence_id=1,
        account_identity=ident,
    )
    tx2 = Transaction(
        transaction_date=date(2026, 4, 10),
        description="Tx Two Afternoon",
        bank_name="ICICI Bank",
        credit=Decimal("100.00"),
        sequence_id=2,
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="ICICI Bank",
        bank_profile="icici",
        account_identity=ident,
        transactions=(tx1, tx2),
    )

    validated = validate_statement_balances(stmt)
    assert len(validated.transactions) == 2
    # Preserves initial order: tx1 followed by tx2
    assert validated.transactions[0].description == "Tx One Morning"
    assert validated.transactions[1].description == "Tx Two Afternoon"


def test_statement_with_invalid_transactions_becomes_invalid() -> None:
    """Test that a statement containing an INVALID transaction is marked INVALID overall."""
    ident = create_account_identity("Axis Bank", "1122334455")

    tx_valid = Transaction(
        transaction_date=date(2026, 5, 1),
        description="Valid Tx",
        bank_name="Axis Bank",
        credit=Decimal("500.00"),
        account_identity=ident,
    )
    tx_invalid = Transaction(
        transaction_date=date(2026, 5, 2),
        description="Missing Both Debit and Credit",
        bank_name="Axis Bank",
        debit=None,
        credit=None,
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="Axis Bank",
        bank_profile="axis",
        account_identity=ident,
        transactions=(tx_valid, tx_invalid),
    )

    validated = validate_statement_balances(stmt)
    assert validated.status == ValidationStatus.INVALID


def test_validator_preserves_all_statement_fields() -> None:
    """Test that validate_statement_balances preserves statement_id, account_holder, ifsc, etc."""
    ident = create_account_identity("Kotak", "4455667788", account_holder="Alice Smith")

    tx = Transaction(
        transaction_date=date(2026, 6, 1),
        description="Coffee",
        bank_name="Kotak",
        debit=Decimal("200.00"),
        account_identity=ident,
    )

    stmt = BankStatement(
        bank_name="Kotak",
        bank_profile="kotak",
        account_identity=ident,
        transactions=(tx,),
        statement_id="stmt_custom_id_123",
        account_holder="Alice Smith",
        account_type="Savings",
        branch="MG Road",
        ifsc="KKBK0000123",
        balance_as_on=Decimal("15000.00"),
    )

    validated = validate_statement_balances(stmt)
    assert validated.statement_id == "stmt_custom_id_123"
    assert validated.account_holder == "Alice Smith"
    assert validated.account_type == "Savings"
    assert validated.branch == "MG Road"
    assert validated.ifsc == "KKBK0000123"
    assert validated.balance_as_on == Decimal("15000.00")
