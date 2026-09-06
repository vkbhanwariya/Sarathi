"""Native PDF format reader leveraging PyMuPDF."""

from __future__ import annotations

import pymupdf

from sarathi.sankalpa import (
    CanonicalDocument,
    PageData,
    ProvenanceRecord,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.native_extraction.readers.common import (
    CAPABILITY_ID,
    PLUGIN_ID,
    STAGE_NAME,
)


def read_pdf(
    data: bytes,
    input_id: str,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract native text, spans, and embedded tables from PDF via PyMuPDF."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    pages: list[PageData] = []
    provenances: list[ProvenanceRecord] = []
    warnings: list[WarningRecord] = []
    full_text_parts: list[str] = []
    all_doc_tables: list[TableData] = []

    try:
        total_pages = len(doc)
        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = doc[page_idx]
            page_text = page.get_text("text").strip()
            if page_text:
                full_text_parts.append(page_text)

            # Extract text spans with font size and formatting evidence
            spans: list[TextSpan] = []
            try:
                page_dict = page.get_text("dict")
                for block in page_dict.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            for s in line.get("spans", []):
                                s_text = s.get("text", "")
                                if isinstance(s_text, str) and s_text.strip():
                                    s_bbox = tuple(float(v) for v in s.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                                    s_size = float(s.get("size", 12.0))
                                    s_font = str(s.get("font", ""))
                                    spans.append(
                                        TextSpan(
                                            text=s_text.strip(),
                                            bounding_box=s_bbox,
                                            metadata={
                                                "font_name": s_font,
                                                "font_size_pt": round(s_size, 1),
                                                "is_heading": s_size >= 14.0,
                                            },
                                        )
                                    )
            except (ValueError, KeyError, TypeError, RuntimeError):
                warnings.append(
                    WarningRecord(
                        code="PDF_RICH_SPAN_EXTRACTION_DEGRADED",
                        message=f"Rich span formatting extraction degraded on page {page_num}; falling back to text blocks.",
                        stage=CAPABILITY_ID,
                    )
                )

            if not spans:
                blocks = page.get_text("blocks")
                for b in blocks:
                    if len(b) >= 5:
                        x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                        if isinstance(text, str) and text.strip():
                            spans.append(
                                TextSpan(
                                    text=text.strip(),
                                    bounding_box=(float(x0), float(y0), float(x1), float(y1)),
                                )
                            )

            # Extract native vector tables if present
            page_tables: list[TableData] = []
            tabs = None
            try:
                tabs = page.find_tables()
            except (pymupdf.FileDataError, ValueError):
                warnings.append(
                    WarningRecord(
                        code="PDF_TABLE_DETECTION_SKIPPED",
                        message="Vector table extraction skipped for page.",
                        stage=STAGE_NAME,
                    )
                )

            if tabs and len(tabs.tables) > 0:
                for t_idx, tab in enumerate(tabs.tables, 1):
                    extracted_rows = tab.extract()
                    if extracted_rows and len(extracted_rows) > 0:
                        headers = tuple(str(h or "") for h in extracted_rows[0])
                        data_rows = tuple(tuple(val for val in row) for row in extracted_rows[1:])
                        t_obj = TableData(
                            name=f"Page_{page_num}_Table_{t_idx}",
                            headers=headers,
                            rows=data_rows,
                        )
                        page_tables.append(t_obj)
                        all_doc_tables.append(t_obj)

            pages.append(
                PageData(
                    page_number=page_num,
                    text=page_text,
                    spans=tuple(spans),
                    tables=tuple(page_tables),
                )
            )

            provenances.append(
                ProvenanceRecord(
                    source_input_id=input_id,
                    stage=STAGE_NAME,
                    plugin_id=PLUGIN_ID,
                    capability_id=CAPABILITY_ID,
                    page_number=page_num,
                    evidence={
                        "reader": "pymupdf",
                        "page_count": total_pages,
                        "has_native_text": bool(page_text),
                        "table_count": len(page_tables),
                    },
                )
            )
    finally:
        doc.close()

    canonical_doc = CanonicalDocument(
        document_id=f"doc-{input_id}",
        source_input_id=input_id,
        pages=tuple(pages),
        tables=tuple(all_doc_tables),
        text="\n\n".join(full_text_parts),
        detected_type="pdf",
    )
    return canonical_doc, tuple(provenances), tuple(warnings)
