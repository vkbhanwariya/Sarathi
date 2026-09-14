"""Native PDF format reader leveraging PyMuPDF."""

from __future__ import annotations

from typing import Any

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
from sarathi.shakti.text.typography import (
    classify_page_lines,
    detect_running_headers_footers,
    normalize_text_spacing,
)

_PDF_TEXT_FLAGS = (
    pymupdf.TEXT_DEHYPHENATE
    | pymupdf.TEXT_PRESERVE_WHITESPACE
    | pymupdf.TEXT_PRESERVE_LIGATURES
)


def read_pdf(
    data: bytes,
    input_id: str,
    use_layout: bool = False,
    skip_header_footer: bool = False,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract native text, spans, and embedded tables from PDF via PyMuPDF or pymupdf-layout."""
    fallback_warning: WarningRecord | None = None
    if use_layout:
        try:
            from sarathi.shakti.native_extraction.readers.pdf_layout import (
                is_layout_package_available,
                read_pdf_with_layout,
            )

            if is_layout_package_available():
                return read_pdf_with_layout(data, input_id, skip_header_footer=skip_header_footer)

            fallback_warning = WarningRecord(
                code="LAYOUT_PACKAGE_UNAVAILABLE",
                message="pymupdf-layout package is not installed; falling back to standard PyMuPDF reader.",
                stage=CAPABILITY_ID,
            )
        except Exception as exc:
            fallback_warning = WarningRecord(
                code="LAYOUT_ANALYSIS_FAILED",
                message=f"Layout analysis failed; falling back to standard reader: {exc}",
                stage=CAPABILITY_ID,
            )

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages: list[PageData] = []
    provenances: list[ProvenanceRecord] = []
    warnings: list[WarningRecord] = [fallback_warning] if fallback_warning else []
    full_text_parts: list[str] = []
    all_doc_tables: list[TableData] = []

    try:
        total_pages = len(doc)
        all_page_blocks: list[list[tuple[str, tuple[float, float, float, float]]]] = []
        page_heights: list[float] = []

        # Pass 1: Collect spatial text blocks for cross-page recurring header/footer analysis
        for page_idx in range(total_pages):
            page = doc[page_idx]
            page_heights.append(float(page.rect.height))
            p_blocks: list[tuple[str, tuple[float, float, float, float]]] = []
            try:
                raw_blocks = page.get_text("blocks")
                for b in raw_blocks:
                    if len(b) >= 5:
                        x0, y0, x1, y1, b_text = b[0], b[1], b[2], b[3], b[4]
                        if isinstance(b_text, str) and b_text.strip():
                            p_blocks.append((b_text.strip(), (float(x0), float(y0), float(x1), float(y1))))
            except Exception:
                pass
            all_page_blocks.append(p_blocks)

        header_templates, footer_templates = (
            detect_running_headers_footers(all_page_blocks, page_heights)
            if total_pages >= 2
            else (set(), set())
        )

        for page_idx in range(total_pages):
            page_num = page_idx + 1
            page = doc[page_idx]
            p_blocks = all_page_blocks[page_idx]
            p_height = page_heights[page_idx]

            body_lines, header_lines, footer_lines = classify_page_lines(
                p_blocks, p_height, header_templates, footer_templates
            )

            if skip_header_footer and (header_lines or footer_lines):
                page_text = normalize_text_spacing("\n\n".join(body_lines))
            else:
                raw_text = page.get_text("text", flags=_PDF_TEXT_FLAGS).strip()
                page_text = normalize_text_spacing(raw_text)

            if page_text:
                full_text_parts.append(page_text)

            page_meta: dict[str, Any] = {}
            if header_lines:
                page_meta["header"] = "\n\n".join(header_lines)
            if footer_lines:
                page_meta["footer"] = "\n\n".join(footer_lines)

            # Extract text spans with font size and formatting evidence
            spans: list[TextSpan] = []
            try:
                page_dict = page.get_text("dict", flags=_PDF_TEXT_FLAGS)
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
                    metadata=page_meta,
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
