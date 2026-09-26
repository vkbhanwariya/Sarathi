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

from sarathi.sankalpa import PageData, TableData, TextSpan


class TableType(StrEnum):
    """Classification for an extracted table."""

    TRANSACTION_TABLE = "transaction_table"
    METADATA_TABLE = "metadata_table"
    SUMMARY_TABLE = "summary_table"
    UNRELATED_TABLE = "unrelated_table"


_HEADER_EXCLUDE_PATTERNS = (
    r"\b(?:postal\s*addr|scheme\s*desc|bank\s*branch|stmt\s*period|statement\s*summary|gstin|email\s*:|customer\s*id)\b",
)

_DATE_HEADER_RE = re.compile(
    r"\b(?:date|txn|tran|post|value|entry|दिनांक|तारीख)\b",
    re.IGNORECASE,
)
_AMOUNT_HEADER_RE = re.compile(
    r"\b(?:debit|credit|withdrawal|deposit|balance|bal|amount|amt|dr|cr|running\s*total|total|line\s*balance|शेष|राशि)\b",
    re.IGNORECASE,
)
_PARTICULARS_HEADER_RE = re.compile(
    r"\b(?:particulars|description|narration|details|part|remarks)\b",
    re.IGNORECASE,
)


def _norm_header_cell(c: Any) -> str:
    s = str(c).strip()
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"[_\.\-/]+", " ", s)
    return s.lower()


def _is_transaction_header_text(text: str) -> bool:
    """Return True if row text contains both date and financial amount indicators without metadata exclusions."""
    norm_text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    norm_text = re.sub(r"[_\.\-/]+", " ", norm_text).lower()
    if any(re.search(pat, norm_text, re.IGNORECASE) for pat in _HEADER_EXCLUDE_PATTERNS):
        return False
    return bool(_DATE_HEADER_RE.search(norm_text) and _AMOUNT_HEADER_RE.search(norm_text))


def _score_header_row(cells: Sequence[Any]) -> int:
    """Score a candidate header row based on presence of distinct canonical header roles."""
    cleaned = [_norm_header_cell(c) for c in cells if c is not None and str(c).strip()]
    if len(cleaned) < 3:
        return 0
    row_text = " ".join(cleaned)
    if any(re.search(pat, row_text, re.IGNORECASE) for pat in _HEADER_EXCLUDE_PATTERNS):
        return 0
    if not (_DATE_HEADER_RE.search(row_text) and _AMOUNT_HEADER_RE.search(row_text)):
        return 0

    score = 4
    if _PARTICULARS_HEADER_RE.search(row_text):
        score += 3
    if re.search(r"\b(?:debit|withdrawal|dr)\b", row_text, re.IGNORECASE):
        score += 2
    if re.search(r"\b(?:credit|deposit|cr)\b", row_text, re.IGNORECASE):
        score += 2
    if re.search(r"\b(?:balance|bal|running\s*total|line\s*balance)\b", row_text, re.IGNORECASE):
        score += 2
    if re.search(r"\b(?:chq|cheque|ref|inst|instrument)\b", row_text, re.IGNORECASE):
        score += 1
    return score


def _has_minimum_header_cells(cells: Sequence[Any], min_cells: int = 3) -> bool:
    """Check if row has at least min_cells distinct non-empty column header strings."""
    non_empty = sum(1 for c in cells if str(c).strip())
    return non_empty >= min_cells


def find_header_row_index(table: TableData) -> int | None:
    """Find the index of the transaction header row in an extracted table, or None.

    If table.headers is populated with transaction headers, returns -1 (headers outside rows).
    Otherwise searches table.rows for embedded header row with the highest score.
    """
    best_idx: int | None = None
    best_score = 0

    if table.headers and _has_minimum_header_cells(table.headers):
        h_score = _score_header_row(table.headers)
        if h_score >= 4:
            best_score = h_score
            best_idx = -1

    if table.rows:
        for r_i, r in enumerate(table.rows[:35]):
            if not _has_minimum_header_cells(r):
                continue
            r_score = _score_header_row(r)
            if r_score > best_score:
                best_score = r_score
                best_idx = r_i
                if r_score >= 12:
                    break

    return best_idx if best_score >= 4 else None


def get_table_header_and_data_rows(
    table: TableData,
    fallback_headers: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]] | None:
    """Extract factual transaction column headers and data rows from TableData."""
    hdr_idx = find_header_row_index(table)
    if hdr_idx is None:
        if fallback_headers is not None and (table.rows or table.headers):
            all_rows = list(table.rows)
            if table.headers and len(table.headers) == len(fallback_headers):
                all_rows.insert(0, tuple(str(c) for c in table.headers))
            return tuple(fallback_headers), tuple(all_rows)
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

    if table.rows:
        from sarathi.shakti.bank_statements.row_classifier import RowType, classify_row

        sample_rows = table.rows[:10]
        tx_count = sum(1 for r in sample_rows if classify_row(r) == RowType.TRANSACTION)
        if tx_count > 0 and (tx_count / len(sample_rows)) >= 0.3:
            return TableType.TRANSACTION_TABLE

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


def reconstruct_borderless_table_from_pages(
    pages: Sequence[PageData],
) -> tuple[TableData | None, TableData | None]:
    """Reconstruct transaction and summary TableData from borderless multi-page text spans."""
    all_spans: list[TextSpan] = [s for p in pages for s in p.spans if s.text and s.text.strip()]
    if not all_spans:
        return None, None

    # 1. Locate header line matching transaction indicator keywords
    hdr_span: TextSpan | None = None
    for s in all_spans:
        s_clean = s.text.strip()
        if _is_transaction_header_text(s_clean) and len(re.split(r"\s{2,}", s_clean)) >= 3:
            hdr_span = s
            break

    if hdr_span is None:
        return None, None

    hdr_text = hdr_span.text.rstrip()

    m_date = re.search(r"\b(?:txn\s*date|date)\b", hdr_text, re.IGNORECASE)
    m_desc = re.search(r"\b(?:transaction\s*description|particulars|narration|description)\b", hdr_text, re.IGNORECASE)
    m_chq = re.search(r"\b(?:cheque\s*no|chq\s*no|ref\s*no)\b", hdr_text, re.IGNORECASE)
    m_val = re.search(r"\b(?:value\s*date|val\s*date)\b", hdr_text, re.IGNORECASE)
    m_dr = re.search(r"\b(?:debit\s*amount|debit|withdrawals)\b", hdr_text, re.IGNORECASE)
    m_cr = re.search(r"\b(?:credit\s*amount|credit|deposits)\b", hdr_text, re.IGNORECASE)

    if not (m_date and m_desc and (m_dr or m_cr)):
        return None, None

    desc_start = m_desc.start()
    chq_start = m_chq.start() if m_chq else desc_start + 40
    val_start = m_val.start() if m_val else chq_start + 20
    val_end = m_val.end() if m_val else val_start + 10
    dr_start = m_dr.start() if m_dr else val_end + 10
    dr_end = m_dr.end() if m_dr else dr_start + 12
    cr_start = m_cr.start() if m_cr else dr_end + 10

    dr_boundary_start = (val_end + dr_start) // 2
    cr_boundary_start = (dr_end + cr_start) // 2

    headers = (
        "Txn Date",
        "Transaction Description",
        "Cheque No",
        "Value Date",
        "Debit Amount",
        "Credit Amount",
        "Running Balance",
    )

    rows: list[tuple[str, ...]] = []
    curr: dict[str, str] | None = None
    summary_found = False
    open_bal_str: str | None = None
    close_bal_str: str | None = None
    total_dr_str: str | None = None
    total_cr_str: str | None = None

    date_start_re = re.compile(r"^(\d{2}[/\-]\d{2}[/\-]\d{2,4})\b")
    amount_re = re.compile(r"^([0-9,]+\.\d{2})\s*$")

    for s in all_spans:
        text = s.text.rstrip()
        if not text.strip():
            continue

        # Header / metadata boundary: commit current transaction and reset curr
        if any(k in text for k in ("Page No", "STATEMENT SUMMARY", "Account Branch", "Statement From", "Statement Summary")):
            if curr is not None:
                rows.append((
                    curr["date"],
                    curr["desc"],
                    curr["chq"],
                    curr["val_date"],
                    curr["debit"],
                    curr["credit"],
                    curr["balance"],
                ))
                curr = None
            if "STATEMENT SUMMARY" in text or "Statement Summary" in text:
                summary_found = True
            continue

        if summary_found:
            m_sum = re.search(r"([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})\s+([0-9,]+\.\d{2})", text)
            if m_sum:
                open_bal_str = m_sum.group(1).replace(",", "")
                total_dr_str = m_sum.group(2).replace(",", "")
                total_cr_str = m_sum.group(3).replace(",", "")
                close_bal_str = m_sum.group(4).replace(",", "")
            continue

        # Skip running headers, page numbers, addresses, account branch, etc.
        if any(
            k in text
            for k in (
                "Txn Date",
                "Address",
                "Opp.Maruthi",
                "RTGS/NEFT",
                "JOINT HOLDERS",
                "Nomination",
                "A/C Open Date",
                "Account Status",
                "CH217",
                "*** End of report ***",
                "**CONTINUE**",
                "Service Tax",
                "Registered Office Address",
            )
        ):
            continue

        m_date_match = date_start_re.match(text)
        if m_date_match:
            if curr is not None:
                rows.append((
                    curr["date"],
                    curr["desc"],
                    curr["chq"],
                    curr["val_date"],
                    curr["debit"],
                    curr["credit"],
                    curr["balance"],
                ))
            curr = {
                "date": text[0:desc_start].strip(),
                "desc": text[desc_start:chq_start].strip(),
                "chq": text[chq_start:val_start].strip() if m_chq else "",
                "val_date": text[val_start:dr_boundary_start].strip() if m_val else "",
                "debit": text[dr_boundary_start:cr_boundary_start].strip(),
                "credit": text[cr_boundary_start:].strip(),
                "balance": "",
            }
        elif curr is not None:
            m_amt = amount_re.match(text.strip())
            if m_amt and not curr["balance"]:
                curr["balance"] = m_amt.group(1).strip()
            else:
                c_desc = text.strip()
                if c_desc and not amount_re.match(c_desc):
                    if not any(
                        k in c_desc
                        for k in (
                            "Email",
                            "Cust ID",
                            "Running Balance",
                            "***",
                            "Opening Balance",
                            "Closing Bal",
                            "Dr Count",
                            "Rohtak Road",
                            "Paschim Vihar",
                            "Page No",
                            "Account Branch",
                        )
                    ):
                        curr["desc"] += " " + c_desc

    if curr is not None:
        rows.append((
            curr["date"],
            curr["desc"],
            curr["chq"],
            curr["val_date"],
            curr["debit"],
            curr["credit"],
            curr["balance"],
        ))

    tx_table = (
        TableData(
            name="borderless_transaction_table",
            headers=headers,
            rows=tuple(rows),
        )
        if rows
        else None
    )

    summary_table = None
    if open_bal_str is not None or close_bal_str is not None:
        sum_headers = ("Opening Balance", "Debits", "Credits", "Closing Balance")
        sum_rows = ((
            open_bal_str or "",
            total_dr_str or "",
            total_cr_str or "",
            close_bal_str or "",
        ),)
        summary_table = TableData(
            name="statement_summary_table",
            headers=sum_headers,
            rows=sum_rows,
        )

    return tx_table, summary_table


def stitch_split_table_rows(tables: list[tuple[int, TableData]]) -> list[tuple[int, TableData]]:
    """Stitch table rows split across consecutive pages by physical PDF page breaks."""
    if len(tables) < 2:
        return tables

    stitched: list[tuple[int, TableData]] = list(tables)
    for i in range(len(stitched) - 1):
        p1, t1 = stitched[i]
        if not t1.rows:
            continue
        r_last = list(t1.rows[-1])

        next_idx = None
        for j in range(i + 1, min(i + 4, len(stitched))):
            cand_t = stitched[j][1]
            cand_len = len(cand_t.headers) if cand_t.headers else (len(cand_t.rows[0]) if cand_t.rows else 0)
            if cand_len == len(r_last):
                next_idx = j
                break
        if next_idx is None:
            continue

        p2, t2 = stitched[next_idx]
        hdr_idx = find_header_row_index(t2)
        if hdr_idx is None and t2.headers:
            r_first = list(t2.headers)
            first_in_headers = True
        elif t2.rows:
            r_first = list(t2.rows[0])
            first_in_headers = False
        else:
            continue

        if not r_first or len(r_last) != len(r_first):
            continue

        d_last = str(r_last[0]).replace("\n", "").strip()
        d_first = str(r_first[0]).replace("\n", "").strip()

        is_split = False
        new_d = d_last
        if re.search(r"\d{1,2}-$|\d{1,2}-\d{1,2}-$", d_last) and re.match(r"^\d{2,4}$|^\d{1,2}-\d{2,4}$", d_first):
            is_split = True
            new_d = d_last + d_first

        if is_split:
            new_last = list(r_last)
            new_last[0] = new_d
            for c_i in range(1, len(r_last)):
                f_val = str(r_first[c_i]).strip()
                if f_val:
                    l_val = str(r_last[c_i]).strip()
                    if l_val:
                        if f_val in ("CR", "DR", "Cr", "Dr"):
                            new_last[c_i] = l_val + f_val
                        else:
                            new_last[c_i] = l_val + " " + f_val
                    else:
                        new_last[c_i] = f_val
            stitched[i] = (p1, TableData(name=t1.name, headers=t1.headers, rows=t1.rows[:-1] + (tuple(new_last),), metadata=t1.metadata))
            if first_in_headers:
                stitched[next_idx] = (p2, TableData(name=t2.name, headers=(), rows=t2.rows, metadata=t2.metadata))
            else:
                stitched[next_idx] = (p2, TableData(name=t2.name, headers=t2.headers, rows=t2.rows[1:], metadata=t2.metadata))

    return stitched
