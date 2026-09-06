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

    # Attempt tabular parsing via polars
    parsed_tabular = False
    try:
        df = pl.read_csv(io.BytesIO(data), encoding=encoding, infer_schema=False)
        if len(df.columns) > 1 or len(df) > 0:
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
    except (pl.exceptions.PolarsError, csv.Error, UnicodeDecodeError):
        # Fallback to stdlib csv
        try:
            sample = text_content[:2048]
            dialect = csv.Sniffer().sniff(sample)
            reader = csv.reader(io.StringIO(text_content), dialect)
            all_rows = list(reader)
            if all_rows and len(all_rows[0]) > 1:
                headers = tuple(all_rows[0])
                rows = tuple(tuple(row) for row in all_rows[1:])
                tables.append(TableData(name="default", headers=headers, rows=rows))
                provenances.append(
                    ProvenanceRecord(
                        source_input_id=input_id,
                        stage=STAGE_NAME,
                        plugin_id=PLUGIN_ID,
                        capability_id=CAPABILITY_ID,
                        evidence={"reader": "csv", "encoding": encoding, "row_count": len(rows)},
                    )
                )
                parsed_tabular = True
        except (csv.Error, UnicodeDecodeError):
            pass

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
        text=text_content.strip() if not parsed_tabular else "",
        detected_type="csv_or_text",
    )
    return canonical_doc, tuple(provenances), tuple(warnings)
