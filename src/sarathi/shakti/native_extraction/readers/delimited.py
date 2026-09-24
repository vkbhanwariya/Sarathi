"""Delimited CSV, TSV, and plain text format reader."""

from __future__ import annotations

import csv
import io

import charset_normalizer
import polars as pl

from sarathi.sankalpa import (
    CanonicalDocument,
    PageData,
    ProvenanceRecord,
    TableData,
    WarningRecord,
)
from sarathi.shakti.native_extraction.readers.common import (
    CAPABILITY_ID,
    PLUGIN_ID,
    STAGE_NAME,
)


def _parse_delimited_blocks(text_content: str, delimiter: str) -> list[TableData]:
    """Parse delimited text into TableData blocks, handling preambles, multi-tables, and quoted rows."""
    reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
    try:
        raw_rows = list(reader)
    except Exception:
        return []
    if not raw_rows:
        return []

    normalized_rows: list[list[str]] = []
    for r in raw_rows:
        if len(r) == 1 and delimiter in r[0]:
            try:
                inner = next(csv.reader([r[0]], delimiter=delimiter))
                if len(inner) > 1:
                    r = inner
            except Exception:
                pass
        normalized_rows.append(r)

    multi_col_rows = [r for r in normalized_rows if len(r) > 1]
    if not multi_col_rows:
        return []

    blocks: list[list[list[str]]] = []
    current_block: list[list[str]] = []
    current_col_count = None
    for r in multi_col_rows:
        if current_col_count is None:
            current_col_count = len(r)
            current_block.append(r)
        elif len(r) == current_col_count:
            current_block.append(r)
        else:
            if len(current_block) >= 2:
                blocks.append(current_block)
            current_block = [r]
            current_col_count = len(r)
    if len(current_block) >= 2:
        blocks.append(current_block)

    tables: list[TableData] = []
    for idx, blk in enumerate(blocks):
        tbl_name = "default" if idx == 0 else f"table_{idx + 1}"
        headers = tuple(blk[0])
        rows = tuple(tuple(r) for r in blk[1:])
        tables.append(TableData(name=tbl_name, headers=headers, rows=rows))
    return tables


def read_csv_or_text(
    data: bytes,
    input_id: str,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract CSV or plain text using polars / stdlib csv with charset-normalizer encoding detection."""
    match = charset_normalizer.from_bytes(data).best()
    encoding = match.encoding if match and match.encoding else "utf-8"
    try:
        text_content = data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text_content = data.decode("utf-8", errors="replace")

    provenances: list[ProvenanceRecord] = []
    warnings: list[WarningRecord] = []
    tables: list[TableData] = []
    pages: list[PageData] = []

    from sarathi.shakti.text.legacy_detection import is_legacy_text

    # Delimiter sniffing for tabular parsing: never treat ';' as delimiter in legacy Hindi text
    delimiter: str | None = None
    sample = text_content[:4096]
    is_legacy = is_legacy_text(sample)
    if not is_legacy:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            delimiter = dialect.delimiter
        except Exception:
            delimiter = None

    if not is_legacy and delimiter is None:
        lines = [line for line in text_content.splitlines() if line.strip()]
        for cand in (",", "\t", "|", ";"):
            if sum(1 for line in lines if cand in line) >= 2:
                delimiter = cand
                break

    # Attempt tabular parsing via multi-block parser or polars
    parsed_tabular = False
    if delimiter is not None:
        extracted_blocks = _parse_delimited_blocks(text_content, delimiter)
        if len(extracted_blocks) > 1:
            tables.extend(extracted_blocks)
            total_rows = sum(len(t.rows) for t in extracted_blocks)
            provenances.append(
                ProvenanceRecord(
                    source_input_id=input_id,
                    stage=STAGE_NAME,
                    plugin_id=PLUGIN_ID,
                    capability_id=CAPABILITY_ID,
                    evidence={"reader": "csv_blocks", "encoding": encoding, "row_count": total_rows},
                )
            )
            parsed_tabular = True
        elif len(extracted_blocks) == 1:
            try:
                read_kwargs: dict[str, str | bool] = {"encoding": encoding, "infer_schema": False, "separator": delimiter}
                df = pl.read_csv(io.BytesIO(data), **read_kwargs)
                if len(df.columns) > 1 and len(df) >= 1:
                    headers = tuple(df.columns)
                    rows = tuple(tuple(str(val) if val is not None else "" for val in row) for row in df.iter_rows())
                    tables.append(TableData(name="default", headers=headers, rows=rows))
                    provenances.append(
                        ProvenanceRecord(
                            source_input_id=input_id,
                            stage=STAGE_NAME,
                            plugin_id=PLUGIN_ID,
                            capability_id=CAPABILITY_ID,
                            evidence={"reader": "polars", "encoding": encoding, "row_count": len(rows)},
                        )
                    )
                    parsed_tabular = True
            except (pl.exceptions.PolarsError, csv.Error, UnicodeDecodeError, Exception):
                tables.append(extracted_blocks[0])
                provenances.append(
                    ProvenanceRecord(
                        source_input_id=input_id,
                        stage=STAGE_NAME,
                        plugin_id=PLUGIN_ID,
                        capability_id=CAPABILITY_ID,
                        evidence={"reader": "csv_blocks", "encoding": encoding, "row_count": len(extracted_blocks[0].rows)},
                    )
                )
                parsed_tabular = True

    if not parsed_tabular:
        # Plain text
        pages.append(PageData(page_number=1, text=text_content.strip()))
        provenances.append(
            ProvenanceRecord(
                source_input_id=input_id,
                stage=STAGE_NAME,
                plugin_id=PLUGIN_ID,
                capability_id=CAPABILITY_ID,
                page_number=1,
                evidence={"reader": "charset_normalizer", "encoding": encoding, "char_count": len(text_content)},
            )
        )

    canonical_doc = CanonicalDocument(
        document_id=f"doc-{input_id}",
        source_input_id=input_id,
        pages=tuple(pages),
        tables=tuple(tables),
        text=text_content.strip(),
        detected_type="csv_or_text",
    )
    return canonical_doc, tuple(provenances), tuple(warnings)
