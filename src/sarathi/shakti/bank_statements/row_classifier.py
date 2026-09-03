"""Raw Row Classifier for Bank Statement Tables."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Sequence


class RowType(StrEnum):
    """Classification type for a raw table row."""

    TRANSACTION = "transaction"
    CONTINUATION = "continuation"
    HEADER = "header"
    OPENING_BALANCE = "opening_balance"
    CLOSING_BALANCE = "closing_balance"
    EOD_BALANCE = "eod_balance"
    SUMMARY = "summary"
    NOISE = "noise"


_HEADER_KEYWORDS = frozenset(
    {"date", "txn date", "transaction date", "particulars", "description", "narration", "debit", "credit", "balance"}
)
_OPENING_KEYWORDS = frozenset({"opening balance", "b/f", "brought forward", "balance b/f", "opening bal"})
_CLOSING_KEYWORDS = frozenset({"closing balance", "c/f", "carried forward", "balance c/f", "closing bal"})
_EOD_KEYWORDS = frozenset({"eod balance", "end of day balance", "daily balance", "eod bal", "daily bal"})
_SUMMARY_KEYWORDS = frozenset({"total", "grand total", "total transactions", "summary"})
_DATE_RE = re.compile(r"\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}|\d{1,2}[/\-\s]+[a-zA-Z]{3,9}[/\-\s]+\d{2,4}")
_NULL_WORDS = frozenset(("", "-", "--", "na", "n/a", "nil", "null"))
_AMOUNT_CELL_RE = re.compile(
    r"^\(?-?(?:[₹$€£]|rs\.?|inr)?\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,4})?\)?(?:\s*(?:dr\.?|cr\.?))?$|^-?\d+\.\d{2}$",
    re.IGNORECASE,
)


def _is_financial_value(val: str) -> bool:
    v = val.strip()
    if not v or v.lower() in _NULL_WORDS:
        return False
    if _AMOUNT_CELL_RE.match(v):
        return True
    return bool(any(ch.isdigit() for ch in v) and re.search(r"\d+\.\d{2}", v))


def classify_row(
    row: Sequence[str],
    date_col_idx: int | None = None,
    amount_col_indices: Sequence[int] | None = None,
) -> RowType:
    """Classify a single row of cell strings from an extracted table."""
    cleaned = [str(c).strip() for c in row]
    if not any(cleaned):
        return RowType.NOISE

    row_str = " ".join(cleaned).lower()

    if any(k in row_str for k in _CLOSING_KEYWORDS):
        return RowType.CLOSING_BALANCE
    if any(k in row_str for k in _OPENING_KEYWORDS):
        return RowType.OPENING_BALANCE
    if any(k in row_str for k in _EOD_KEYWORDS):
        return RowType.EOD_BALANCE
    if any(row_str.startswith(k) or f" {k} " in f" {row_str} " for k in _SUMMARY_KEYWORDS):
        return RowType.SUMMARY
    if sum(1 for k in _HEADER_KEYWORDS if k in row_str) >= 2 and not _DATE_RE.search(row_str):
        return RowType.HEADER

    check_cells = [cleaned[date_col_idx]] if date_col_idx is not None and date_col_idx < len(cleaned) else cleaned
    if any(_DATE_RE.search(c) for c in check_cells):
        return RowType.TRANSACTION

    # A row with financial figures (Debit, Credit, Amount, or Balance) but no date
    # is a distinct Transaction subject to date-inheritance resolution, never continuation.
    if amount_col_indices:
        for idx in amount_col_indices:
            if idx is not None and idx < len(cleaned) and _is_financial_value(cleaned[idx]):
                return RowType.TRANSACTION
    else:
        if any(_is_financial_value(c) for c in cleaned):
            return RowType.TRANSACTION

    return RowType.CONTINUATION if len(row_str) > 3 else RowType.NOISE
