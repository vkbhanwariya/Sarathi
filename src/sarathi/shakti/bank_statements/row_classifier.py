"""Raw Row Classifier for Bank Statement Tables.

Classifies raw table rows into:
- TRANSACTION
- CONTINUATION
- HEADER
- OPENING_BALANCE
- CLOSING_BALANCE
- SUMMARY
- NOISE
"""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Sequence


class RowType(StrEnum):
    """Classification type for a raw table row."""

    TRANSACTION = "transaction"
    CONTINUATION = "continuation"
    HEADER = "header"
    OPENING_BALANCE = "opening_balance"
    CLOSING_BALANCE = "closing_balance"
    SUMMARY = "summary"
    NOISE = "noise"


_HEADER_KEYWORDS = {"date", "txn date", "transaction date", "particulars", "description", "narration", "debit", "credit", "balance"}
_OPENING_KEYWORDS = {"opening balance", "b/f", "brought forward", "balance b/f", "opening bal"}
_CLOSING_KEYWORDS = {"closing balance", "c/f", "carried forward", "balance c/f", "closing bal"}
_SUMMARY_KEYWORDS = {"total", "grand total", "total transactions", "summary"}


def classify_row(row: Sequence[str], date_col_idx: int | None = None) -> RowType:
    """Classify a single row of cell strings from an extracted table."""
    cleaned_cells = [str(c).strip() for c in row]
    row_str = " ".join(cleaned_cells).lower()

    if not any(cleaned_cells):
        return RowType.NOISE

    # Check closing balance before opening balance keywords
    if any(k in row_str for k in _CLOSING_KEYWORDS):
        return RowType.CLOSING_BALANCE

    # Check opening balance
    if any(k in row_str for k in _OPENING_KEYWORDS):
        return RowType.OPENING_BALANCE

    # Check summary/totals
    if any(row_str.startswith(k) or f" {k} " in f" {row_str} " for k in _SUMMARY_KEYWORDS):
        return RowType.SUMMARY

    # Check header
    if any(k in row_str for k in _HEADER_KEYWORDS) and not re.search(r"\d{2}[/\-]\d{2}[/\-]\d{4}", row_str):
        matches = sum(1 for k in _HEADER_KEYWORDS if k in row_str)
        if matches >= 2:
            return RowType.HEADER

    # Check transaction date pattern if date column is known
    if date_col_idx is not None and date_col_idx < len(cleaned_cells):
        date_cell = cleaned_cells[date_col_idx]
        if re.search(r"\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}", date_cell) or re.search(r"\d{1,2}\s+[a-zA-Z]{3,9}\s+\d{4}", date_cell):
            return RowType.TRANSACTION

    # Check any cell for date pattern
    for c in cleaned_cells:
        if re.search(r"\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}", c) or re.search(r"\d{1,2}\s+[a-zA-Z]{3,9}\s+\d{4}", c):
            return RowType.TRANSACTION

    # Otherwise if it has text in description column, it may be multiline continuation
    if len(row_str) > 3:
        return RowType.CONTINUATION

    return RowType.NOISE
