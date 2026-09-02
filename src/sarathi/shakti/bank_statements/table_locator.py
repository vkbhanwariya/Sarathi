"""Table Locator and Classifier for Bank Statements in Sarathi V2.

Classifies extracted tables in a CanonicalDocument into:
- TRANSACTION_TABLE
- METADATA_TABLE
- SUMMARY_TABLE
- UNRELATED_TABLE
"""

from __future__ import annotations

from enum import StrEnum

from sarathi.sankalpa import TableData


class TableType(StrEnum):
    """Classification for an extracted table."""

    TRANSACTION_TABLE = "transaction_table"
    METADATA_TABLE = "metadata_table"
    SUMMARY_TABLE = "summary_table"
    UNRELATED_TABLE = "unrelated_table"


def find_header_row_index(table: TableData) -> int | None:
    """Find the index of the transaction header row in an extracted table, or None.

    If table.headers is populated with transaction headers, returns -1 (headers outside rows).
    Otherwise searches table.rows for embedded header row.
    """
    if table.headers:
        h_str = " ".join(str(c).lower().strip() for c in table.headers)
        has_date = any(d in h_str for d in ("date", "txn", "दिनांक", "तारीख"))
        has_amount = any(
            a in h_str
            for a in ("debit", "credit", "withdrawal", "deposit", "amount", "dr", "cr", "balance", "bal", "शेष")
        )
        if has_date and has_amount:
            return -1

    if not table.rows:
        return None

    for r_i, r in enumerate(table.rows):
        r_str = " ".join(str(c).lower().strip() for c in r)
        has_date = any(d in r_str for d in ("date", "txn", "दिनांक", "तारीख"))
        has_amount = any(
            a in r_str
            for a in ("debit", "credit", "withdrawal", "deposit", "amount", "dr", "cr", "balance", "bal", "शेष")
        )
        if has_date and has_amount:
            return r_i
    return None


def get_table_header_and_data_rows(
    table: TableData,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]] | None:
    """Extract factual transaction column headers and data rows from TableData."""
    hdr_idx = find_header_row_index(table)
    if hdr_idx is None:
        return None

    if hdr_idx == -1 and table.headers:
        return tuple(str(c) for c in table.headers), table.rows

    if hdr_idx >= 0 and len(table.rows) > hdr_idx:
        return tuple(str(c) for c in table.rows[hdr_idx]), table.rows[hdr_idx + 1 :]

    return None


def classify_table(table: TableData) -> TableType:
    """Classify an extracted table based on header and row density."""
    if find_header_row_index(table) is not None:
        return TableType.TRANSACTION_TABLE

    if not table.rows and not table.headers:
        return TableType.UNRELATED_TABLE

    first_row = [str(c).lower().strip() for c in (table.headers if table.headers else table.rows[0])]
    header_str = " ".join(first_row)

    if any(m in header_str for m in ("account no", "account name", "ifsc", "branch", "customer id")):
        return TableType.METADATA_TABLE

    if any(s in header_str for s in ("total", "opening balance", "closing balance", "summary")):
        return TableType.SUMMARY_TABLE

    return TableType.UNRELATED_TABLE
