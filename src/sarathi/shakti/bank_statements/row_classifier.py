"""Raw Row Classifier for Bank Statement Tables."""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum


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
_OPENING_PHRASES = frozenset(
    {
        "opening balance",
        "brought forward",
        "brought forword",
        "balance b/f",
        "opening bal",
        "balance b/d",
        "bal b/f",
        "bal b/d",
        "b/f",
        "b/d",
    }
)
_CLOSING_PHRASES = frozenset(
    {
        "closing balance",
        "carried forward",
        "balance c/f",
        "closing bal",
        "balance c/d",
        "bal c/f",
        "bal c/d",
        "c/f",
        "c/d",
    }
)
_SHORT_OPENING_RE = re.compile(
    r"(?:\b|\s)(?:bal(?:ance)?|opening)\s+(?:b/f|b/d)(?:\b|\s)|(?:^|\|)[\s\.\-_]*(?:b/f|b/d)[\s\.\-_]*(?:$|\|)",
    re.IGNORECASE,
)
_SHORT_CLOSING_RE = re.compile(
    r"(?:\b|\s)(?:bal(?:ance)?|closing)\s+(?:c/f|c/d)(?:\b|\s)|(?:^|\|)[\s\.\-_]*(?:c/f|c/d)[\s\.\-_]*(?:$|\|)",
    re.IGNORECASE,
)
_EOD_KEYWORDS = frozenset({"eod balance", "end of day balance", "daily balance", "eod bal", "daily bal"})
_SUMMARY_KEYWORDS = frozenset({"total", "grand total", "total transactions", "summary"})
_TX_ACTION_KEYWORDS = frozenset(
    {
        "fee", "fees", "charge", "charges", "chg", "tax", "gst", "interest",
        "transfer", "pos", "upi", "neft", "rtgs", "imps", "cash",
        "atm", "chq", "cheque", "commission", "refund", "purchase", "bill",
    }
)
_DATE_RE = re.compile(
    r"\d{4}[/\-]\d{1,2}[/\-]\d{1,2}|\d{1,2}[/\-\s]\d{1,2}[/\-\s]\d{2,4}|\d{1,2}[/\-\s]+[a-zA-Z]{3,9}[/\-\s]+\d{2,4}"
)
_NULL_WORDS = frozenset(("", "-", "--", "na", "n/a", "nil", "null"))
_AMOUNT_CELL_RE = re.compile(
    r"^\(?-?(?:[₹$€£]|rs\.?|inr)?\s*\d{1,3}(?:,\d{3})*(?:\.\d{1,4})?\)?(?:\s*(?:dr\.?|cr\.?))?$|^-?\d+\.\d{2}$|^-?\d+$",
    re.IGNORECASE,
)


def _is_financial_value(val: str) -> bool:
    v = val.strip()
    if not v or v.lower() in _NULL_WORDS:
        return False
    if _AMOUNT_CELL_RE.match(v):
        return True
    return bool(any(ch.isdigit() for ch in v) and re.search(r"\d+\.\d{2}", v))


def _has_short_opening(cleaned_cells: Sequence[str]) -> bool:
    for c in cleaned_cells:
        c_clean = c.strip().lower()
        if c_clean in ("b/f", "b/d", "bal b/f", "bal b/d", "balance b/f", "balance b/d"):
            return True
        if _SHORT_OPENING_RE.search(c_clean):
            return True
    return False


def _has_short_closing(cleaned_cells: Sequence[str]) -> bool:
    for c in cleaned_cells:
        c_clean = c.strip().lower()
        if c_clean in ("c/f", "c/d", "bal c/f", "bal c/d", "balance c/f", "balance c/d"):
            return True
        if _SHORT_CLOSING_RE.search(c_clean):
            return True
    return False


def classify_row(
    row: Sequence[str],
    date_col_idx: int | None = None,
    amount_col_indices: Sequence[int] | None = None,
    balance_col_idx: int | None = None,
) -> RowType:
    """Classify a single row of cell strings from an extracted table."""
    cleaned = [str(c).strip() for c in row]
    if not any(cleaned):
        return RowType.NOISE

    row_str = " ".join(cleaned).lower()

    if any(k in row_str for k in ("elapsed:", "legend :", "end of statement", "end of the statement", "statement summary", "dr count", "cr count", "page no .:")):
        return RowType.NOISE

    if all(re.match(r"^[\*\-_=\.]+$", c) for c in cleaned if c):
        return RowType.NOISE

    if any(re.match(r"^[\*\-_=\.]{3,}$", c) for c in cleaned if c) and not any(_DATE_RE.search(c) for c in cleaned):
        return RowType.NOISE

    check_cells = [cleaned[date_col_idx]] if date_col_idx is not None and date_col_idx < len(cleaned) else cleaned
    has_date = any(_DATE_RE.search(c) for c in check_cells)

    # Determine financial presence: distinguish transaction movement from balance
    has_financial = False
    has_tx_amount = False

    if amount_col_indices:
        tx_amount_indices = [idx for idx in amount_col_indices if idx != balance_col_idx]
        for idx in tx_amount_indices:
            if idx is not None and idx < len(cleaned) and _is_financial_value(cleaned[idx]):
                has_tx_amount = True
                has_financial = True
                break
        if not has_financial and balance_col_idx is not None and balance_col_idx < len(cleaned):
            if _is_financial_value(cleaned[balance_col_idx]):
                has_financial = True
    else:
        financial_cells = [c for c in cleaned if _is_financial_value(c)]
        has_financial = bool(financial_cells)
        # If there are >= 2 financial numbers, the row has both transaction amount and balance
        has_tx_amount = len(financial_cells) >= 2

    has_tx_keywords = any(k in row_str for k in _TX_ACTION_KEYWORDS)

    # Opening/Closing balance checks (only valid if not a fee/charge/action transaction)
    if not has_tx_keywords:
        is_closing = any(k in row_str for k in _CLOSING_PHRASES) or _has_short_closing(cleaned)
        is_opening = any(k in row_str for k in _OPENING_PHRASES) or _has_short_opening(cleaned)

        if is_closing:
            if not has_tx_amount or any(k in row_str for k in _CLOSING_PHRASES) or _has_short_closing(cleaned):
                return RowType.CLOSING_BALANCE
        if is_opening:
            if not has_tx_amount or any(k in row_str for k in _OPENING_PHRASES) or _has_short_opening(cleaned):
                return RowType.OPENING_BALANCE

    if any(k in row_str for k in _EOD_KEYWORDS):
        return RowType.EOD_BALANCE

    # A row with date and clear transaction amount (debit/credit) or financial presence
    # is definitely a transaction, not a summary or header
    if has_date and (has_tx_amount or has_financial):
        return RowType.TRANSACTION

    # Check for summary row when not an active transaction with a date
    if any(row_str.startswith(k) or f" {k} " in f" {row_str} " for k in _SUMMARY_KEYWORDS):
        return RowType.SUMMARY

    if sum(1 for k in _HEADER_KEYWORDS if k in row_str) >= 2 and not has_date:
        return RowType.HEADER

    if has_date:
        return RowType.TRANSACTION

    # A row with financial figures (Debit, Credit, Amount, or Balance) but no date
    # is a distinct Transaction subject to date-inheritance resolution, never continuation.
    if has_financial:
        return RowType.TRANSACTION

    return RowType.CONTINUATION if len(row_str) > 3 else RowType.NOISE
