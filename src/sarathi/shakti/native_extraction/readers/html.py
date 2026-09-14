"""HTML table and markup reader leveraging BeautifulSoup."""

from __future__ import annotations

from typing import Any

import charset_normalizer
from bs4 import BeautifulSoup

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


def read_html_table(
    data: bytes,
    input_id: str,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract tables or text from HTML markup (including disguised .xls) via BeautifulSoup."""
    tables: list[TableData] = []
    provenances: list[ProvenanceRecord] = []
    warnings: list[WarningRecord] = []

    match = charset_normalizer.from_bytes(data).best()
    encoding = match.encoding if match and match.encoding else "utf-8"
    try:
        html_text = data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        html_text = data.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html_text, "html.parser")
    html_tables = soup.find_all("table")

    if html_tables and len(html_tables) > 0:
        for t_idx, t_tag in enumerate(html_tables, 1):
            rows: list[tuple[Any, ...]] = []
            headers: tuple[str, ...] = ()
            for tr_idx, tr in enumerate(t_tag.find_all("tr")):
                th_cells = [th.get_text(strip=True) for th in tr.find_all("th")]
                td_cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if tr_idx == 0 and th_cells:
                    headers = tuple(th_cells)
                elif tr_idx == 0 and td_cells and not headers:
                    headers = tuple(td_cells)
                else:
                    if td_cells:
                        rows.append(tuple(td_cells))

            table_name = t_tag.get("id") or t_tag.get("name") or f"Table_{t_idx}"
            tables.append(
                TableData(
                    name=str(table_name),
                    headers=headers,
                    rows=tuple(rows),
                )
            )
            provenances.append(
                ProvenanceRecord(
                    source_input_id=input_id,
                    stage=STAGE_NAME,
                    plugin_id=PLUGIN_ID,
                    capability_id=CAPABILITY_ID,
                    evidence={"reader": "beautifulsoup4", "table_name": str(table_name), "row_count": len(rows)},
                )
            )
        pages: tuple[PageData, ...] = ()
        doc_text = ""
    else:
        # Fallback to plain text extracted from body
        doc_text = soup.get_text(separator="\n", strip=True)
        pages = (PageData(page_number=1, text=doc_text),)
        provenances.append(
            ProvenanceRecord(
                source_input_id=input_id,
                stage=STAGE_NAME,
                plugin_id=PLUGIN_ID,
                capability_id=CAPABILITY_ID,
                page_number=1,
                evidence={"reader": "beautifulsoup4", "type": "html_text"},
            )
        )

    canonical_doc = CanonicalDocument(
        document_id=f"doc-{input_id}",
        source_input_id=input_id,
        pages=pages,
        tables=tuple(tables),
        text=doc_text,
        detected_type="html_table",
    )
    return canonical_doc, tuple(provenances), tuple(warnings)
