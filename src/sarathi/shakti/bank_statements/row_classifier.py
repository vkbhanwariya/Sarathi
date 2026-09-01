"""Raw Row Classifier for Bank Statement Tables."""

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


_HEADER_KEYWORDS = frozenset({"date", "txn date", "transaction date", "particulars", "description", "narration", "debit", "credit", "balance"})
_OPENING_KEYWORDS = frozenset({"opening balance", "b/f", "brought forward", "balance b/f", "opening bal"})
_CLOSING_KEYWORDS = frozenset({"closing balance", "c/f", "carried forward", "balance c/f", "closing bal"})
_SUMMARY_KEYWORDS = frozenset({"total", "grand total", "total transactions", "summary"})
_DATE_RE = re.compile(r"\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}|\d{1,2}[/\-\s]+[a-zA-Z]{3,9}[/\-\s]+\d{2,4}")


def classify_row(row: Sequence[str], date_col_idx: int | None = None) -> RowType:
    """Classify a single row of cell strings from an extracted table."""
    cleaned = [str(c).strip() for c in row]
    if not any(cleaned):
        return RowType.NOISE

    row_str = " ".join(cleaned).lower()

    if any(k in row_str for k in _CLOSING_KEYWORDS):
        return RowType.CLOSING_BALANCE
    if any(k in row_str for k in _OPENING_KEYWORDS):
        return RowType.OPENING_BALANCE
    if any(row_str.startswith(k) or f" {k} " in f" {row_str} " for k in _SUMMARY_KEYWORDS):
        return RowType.SUMMARY
    if sum(1 for k in _HEADER_KEYWORDS if k in row_str) >= 2 and not _DATE_RE.search(row_str):
        return RowType.HEADER

    check_cells = [cleaned[date_col_idx]] if date_col_idx is not None and date_col_idx < len(cleaned) else cleaned
    if any(_DATE_RE.search(c) for c in check_cells):
        return RowType.TRANSACTION

    return RowType.CONTINUATION if len(row_str) > 3 else RowType.NOISE
