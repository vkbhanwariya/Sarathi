"""Tests for Raw Row Classification."""

import pytest

from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row


def test_classify_transaction_row() -> None:
    row = ["01/01/2026", "UPI-1234-Merchant", "UPI1234", "100.00", "", "5000.00"]
    assert classify_row(row, date_col_idx=0) == RowType.TRANSACTION


def test_classify_opening_balance_row() -> None:
    row = ["01/01/2026", "OPENING BALANCE", "", "", "", "5100.00"]
    assert classify_row(row) == RowType.OPENING_BALANCE


def test_classify_closing_balance_row() -> None:
    row = ["31/01/2026", "CLOSING BALANCE B/F", "", "", "", "10500.00"]
    assert classify_row(row) == RowType.CLOSING_BALANCE


def test_classify_noise_and_summary_row() -> None:
    assert classify_row(["", "", "", ""]) == RowType.NOISE
    assert classify_row(["Total Debits / Credits", "1000.00", "5000.00"]) == RowType.SUMMARY
