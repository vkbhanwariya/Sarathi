"""Table Locator and Classifier for Bank Statements in Sarathi.

Classifies extracted tables in a CanonicalDocument into:
- TRANSACTION_TABLE
- METADATA_TABLE
- SUMMARY_TABLE
- UNRELATED_TABLE
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from sarathi.sankalpa import TableData, TextSpan


class TableType(StrEnum):
    """Classification for an extracted table."""

    TRANSACTION_TABLE = "transaction_table"
    METADATA_TABLE = "metadata_table"
    SUMMARY_TABLE = "summary_table"
    UNRELATED_TABLE = "unrelated_table"


_DATE_TOKENS = ("date", "txn", "tran", "dt", "post", "entry", "दिनांक", "तारीख")
_AMOUNT_TOKENS = (
    "debit",
    "credit",
    "withdrawal",
    "withdraw",
    "deposit",
    "dep",
    "amount",
    "dr",
    "cr",
    "balance",
    "bal",
    "शेष",
    "राशि",
)


def _is_transaction_header_text(text: str) -> bool:
    """Return True if row text contains both date and financial amount indicators."""
    return any(d in text for d in _DATE_TOKENS) and any(a in text for a in _AMOUNT_TOKENS)


def _has_minimum_header_cells(cells: Sequence[Any], min_cells: int = 3) -> bool:
    """Check if row has at least min_cells distinct non-empty column header strings."""
    non_empty = sum(1 for c in cells if str(c).strip())
    return non_empty >= min_cells


def find_header_row_index(table: TableData) -> int | None:
    """Find the index of the transaction header row in an extracted table, or None.

    If table.headers is populated with transaction headers, returns -1 (headers outside rows).
    Otherwise searches table.rows for embedded header row.
    """
    if table.headers and _has_minimum_header_cells(table.headers):
        h_str = " ".join(str(c).lower().strip() for c in table.headers)
        if _is_transaction_header_text(h_str):
            return -1

    if not table.rows:
        return None

    for r_i, r in enumerate(table.rows):
        if not _has_minimum_header_cells(r):
            continue
        r_str = " ".join(str(c).lower().strip() for c in r)
        if _is_transaction_header_text(r_str):
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
        raw_headers, raw_data_rows = tuple(str(c) for c in table.headers), table.rows
    elif hdr_idx >= 0 and len(table.rows) > hdr_idx:
        raw_headers, raw_data_rows = tuple(str(c) for c in table.rows[hdr_idx]), table.rows[hdr_idx + 1 :]
    else:
        return None

    # Handle spreadsheets with merged cells where header strings occupy a single cell in a wide span
    if raw_headers and sum(1 for c in raw_headers if not str(c).strip()) > len(raw_headers) // 2:
        hdr_positions = [(i, str(h).strip()) for i, h in enumerate(raw_headers) if str(h).strip()]
        if hdr_positions and raw_data_rows:
            col_counts = {
                c_i: sum(1 for r in raw_data_rows if c_i < len(r) and str(r[c_i]).strip())
                for c_i in range(len(raw_headers))
            }
            active_cols = [c_i for c_i, cnt in col_counts.items() if cnt > 0]
            if active_cols:
                aligned = [""] * len(raw_headers)
                for h_i, h_text in hdr_positions:
                    candidates = [a for a in active_cols if abs(a - h_i) <= 5]
                    if candidates:
                        best_c = max(candidates, key=lambda a: (col_counts[a], -abs(a - h_i)))
                        aligned[best_c] = h_text
                    else:
                        aligned[h_i] = h_text
                return tuple(aligned), raw_data_rows

    return raw_headers, raw_data_rows


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


def reconstruct_table_from_spans(spans: Sequence[TextSpan]) -> TableData | None:
    """Reconstruct a tabular grid structure from spatially positioned text spans."""
    valid_spans = [s for s in spans if s.bounding_box is not None and s.text.strip()]
    if len(valid_spans) < 4:
        return None

    # Group spans into rows by vertical proximity
    sorted_spans = sorted(valid_spans, key=lambda s: (s.bounding_box[1], s.bounding_box[0]))  # type: ignore[index]

    rows_spans: list[list[TextSpan]] = []
    for s in sorted_spans:
        bbox = s.bounding_box
        assert bbox is not None
        placed = False
        for row in reversed(rows_spans):
            ref_bbox = row[0].bounding_box
            assert ref_bbox is not None
            row_h = max(10.0, ref_bbox[3] - ref_bbox[1])
            y_mid_s = (bbox[1] + bbox[3]) / 2
            y_mid_ref = (ref_bbox[1] + ref_bbox[3]) / 2
            if abs(y_mid_s - y_mid_ref) <= row_h * 0.6:
                row.append(s)
                placed = True
                break
            # Since sorted_spans is ordered by Y (ascending), earlier rows in rows_spans
            # have even smaller y_mid_ref. If current span is already far below, prune search.
            if (y_mid_s - y_mid_ref) > row_h * 2.0:
                break
        if not placed:
            rows_spans.append([s])

    if len(rows_spans) < 2:
        return None

    # Sort each row horizontally by x0
    for row in rows_spans:
        row.sort(key=lambda s: s.bounding_box[0] if s.bounding_box else 0.0)

    # Find the header row matching transaction indicators
    header_idx = -1
    for r_i, row in enumerate(rows_spans):
        row_text = " ".join(s.text.lower().strip() for s in row)
        if _is_transaction_header_text(row_text) and len(row) >= 3:
            header_idx = r_i
            break

    if header_idx < 0:
        return None

    header_spans = rows_spans[header_idx]
    headers = tuple(s.text.strip() for s in header_spans)
    col_centers = [(s.bounding_box[0] + s.bounding_box[2]) / 2 for s in header_spans if s.bounding_box]

    data_rows: list[tuple[str, ...]] = []
    for row in rows_spans[header_idx + 1 :]:
        if not row:
            continue
        cells = [""] * len(col_centers)
        for s in row:
            if not s.bounding_box:
                continue
            s_center = (s.bounding_box[0] + s.bounding_box[2]) / 2
            closest_col = min(range(len(col_centers)), key=lambda c_i: abs(col_centers[c_i] - s_center))
            if cells[closest_col]:
                cells[closest_col] += " " + s.text.strip()
            else:
                cells[closest_col] = s.text.strip()
        if any(c for c in cells):
            data_rows.append(tuple(cells))

    if not data_rows:
        return None

    return TableData(
        name="scanned_ocr_table",
        headers=headers,
        rows=tuple(data_rows),
    )


def reconstruct_table_from_text(text: str) -> TableData | None:
    """Reconstruct TableData from delimiter-separated or tabular text."""
    if not text or not text.strip():
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None

    parsed_rows: list[list[str]] = []
    for line in lines:
        if "," in line:
            import csv

            try:
                parts = [p.strip() for p in next(csv.reader([line]))]
            except (csv.Error, StopIteration):
                parts = [p.strip() for p in line.split(",")]
        elif "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
        elif "  " in line:
            parts = [p.strip() for p in re.split(r"\s{2,}", line)]
        else:
            parts = [line]
        parsed_rows.append(parts)

    header_idx = -1
    for r_i, r in enumerate(parsed_rows):
        r_str = " ".join(c.lower() for c in r)
        if _is_transaction_header_text(r_str) and len([c for c in r if c]) >= 3:
            header_idx = r_i
            break

    if header_idx < 0:
        return None

    headers = tuple(parsed_rows[header_idx])
    col_count = len(headers)
    data_rows: list[tuple[str, ...]] = []
    for r in parsed_rows[header_idx + 1 :]:
        if not any(r):
            continue
        if len(r) < col_count:
            r = r + [""] * (col_count - len(r))
        elif len(r) > col_count:
            r = r[: col_count - 1] + [" ".join(r[col_count - 1 :])]
        data_rows.append(tuple(r))

    if not data_rows:
        return None

    return TableData(
        name="text_table",
        headers=headers,
        rows=tuple(data_rows),
    )
