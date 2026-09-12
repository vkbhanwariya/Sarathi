"""GNN-powered PDF layout analysis reader leveraging pymupdf-layout."""

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
from sarathi.shakti.text.typography import normalize_text_spacing, reconstruct_line_from_spans

_PDF_TEXT_FLAGS = (
    pymupdf.TEXT_DEHYPHENATE
    | pymupdf.TEXT_PRESERVE_WHITESPACE
    | pymupdf.TEXT_PRESERVE_LIGATURES
)

# Semantic heading classes identified by BoxRFDGNN
_HEADING_CLASSES = frozenset({"title", "section-header"})
_HEADER_FOOTER_CLASSES = frozenset({"page-header", "page-footer"})


def is_layout_package_available() -> bool:
    """Return True if pymupdf-layout is installed and operational."""
    try:
        import pymupdf.layout  # noqa: F401

        return True
    except (ImportError, RuntimeError):
        return False


def _point_in_bbox(px: float, py: float, bbox: tuple[float, float, float, float], margin: float = 3.0) -> bool:
    x0, y0, x1, y1 = bbox
    return (x0 - margin) <= px <= (x1 + margin) and (y0 - margin) <= py <= (y1 + margin)


def read_pdf_with_layout(
    data: bytes,
    input_id: str,
    skip_header_footer: bool = False,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract structured document content using GNN page layout analysis.

    Uses Graph Neural Networks (BoxRFDGNN) trained on PDF vector topologies to
    extract semantic entities (title, section-header, list-item, table, page-header, page-footer),
    resolve multi-column topological reading order, and isolate table grids.
    """
    import pymupdf.layout as _pymupdf_layout  # noqa: F401 # Ensures activation of pymupdf._get_layout

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

            # Execute GNN layout analysis on page
            layout_items: list[list[Any]] = []
            try:
                page.get_layout()
                layout_items = page.layout_information or []
            except Exception as layout_exc:
                warnings.append(
                    WarningRecord(
                        code="LAYOUT_ANALYSIS_DEGRADED",
                        message=f"GNN layout analysis degraded on page {page_num}: {layout_exc}",
                        stage=CAPABILITY_ID,
                    )
                )

            # Extract raw rich lines and spans from page with font-metric whitespace preservation
            raw_lines: list[dict[str, Any]] = []
            try:
                page_dict = page.get_text("dict", flags=_PDF_TEXT_FLAGS)
                for block in page_dict.get("blocks", []):
                    if "lines" in block:
                        for line in block["lines"]:
                            line_spans_data: list[tuple[str, tuple[float, float, float, float], float]] = []
                            spans_objs: list[TextSpan] = []
                            l_bbox = tuple(float(v) for v in line.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                            for s in line.get("spans", []):
                                s_text = s.get("text", "")
                                if isinstance(s_text, str) and s_text:
                                    s_bbox = tuple(float(v) for v in s.get("bbox", (0.0, 0.0, 0.0, 0.0)))
                                    s_size = float(s.get("size", 12.0))
                                    s_font = str(s.get("font", ""))
                                    line_spans_data.append((s_text, s_bbox, s_size))
                                    if s_text.strip():
                                        spans_objs.append(
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
                            if line_spans_data:
                                line_str = reconstruct_line_from_spans(line_spans_data)
                                lcx = (l_bbox[0] + l_bbox[2]) / 2.0
                                lcy = (l_bbox[1] + l_bbox[3]) / 2.0
                                raw_lines.append({
                                    "bbox": l_bbox,
                                    "cx": lcx,
                                    "cy": lcy,
                                    "line_text": line_str,
                                    "spans": spans_objs,
                                })
            except Exception:
                warnings.append(
                    WarningRecord(
                        code="PDF_RICH_SPAN_EXTRACTION_DEGRADED",
                        message=f"Rich span extraction degraded on page {page_num}.",
                        stage=CAPABILITY_ID,
                    )
                )

            # Map lines and spans to GNN layout items and assign semantic labels
            ordered_spans: list[TextSpan] = []
            classes_detected: set[str] = set()
            assigned_line_indices: set[int] = set()
            item_blocks: list[tuple[str, list[str]]] = []

            if layout_items:
                for item_idx, item in enumerate(layout_items):
                    x0, y0, x1, y1, cls_name = float(item[0]), float(item[1]), float(item[2]), float(item[3]), str(item[4])
                    classes_detected.add(cls_name)
                    item_bbox = (x0, y0, x1, y1)

                    is_hdr_ftr = cls_name in _HEADER_FOOTER_CLASSES
                    is_hdg = cls_name in _HEADING_CLASSES
                    hdg_lvl = 1 if cls_name == "title" else (2 if cls_name == "section-header" else None)

                    item_lines: list[str] = []
                    for l_idx, line_info in enumerate(raw_lines):
                        if l_idx not in assigned_line_indices and _point_in_bbox(line_info["cx"], line_info["cy"], item_bbox):
                            assigned_line_indices.add(l_idx)
                            item_lines.append(line_info["line_text"])
                            for span in line_info["spans"]:
                                meta = dict(span.metadata)
                                meta["layout_class"] = cls_name
                                meta["layout_order"] = item_idx
                                if is_hdg:
                                    meta["is_heading"] = True
                                    meta["heading_level"] = hdg_lvl
                                if is_hdr_ftr:
                                    meta["is_header_footer"] = True

                                ordered_spans.append(
                                    TextSpan(
                                        text=span.text,
                                        bounding_box=span.bounding_box,
                                        confidence=span.confidence,
                                        language=span.language,
                                        script=span.script,
                                        metadata=meta,
                                    )
                                )
                    if item_lines:
                        item_blocks.append((cls_name, item_lines))

            # Append any unassigned lines in their natural spatial order
            unassigned_lines: list[str] = []
            for l_idx, line_info in enumerate(raw_lines):
                if l_idx not in assigned_line_indices:
                    unassigned_lines.append(line_info["line_text"])
                    ordered_spans.extend(line_info["spans"])

            if unassigned_lines:
                item_blocks.append(("unassigned", unassigned_lines))

            # Extract tables with GNN neural table region guidance
            page_tables: list[TableData] = []
            table_layout_items = [item for item in layout_items if len(item) >= 5 and item[4] == "table"]

            if table_layout_items:
                for t_idx, t_item in enumerate(table_layout_items, 1):
                    clip_rect = pymupdf.Rect(float(t_item[0]), float(t_item[1]), float(t_item[2]), float(t_item[3]))
                    try:
                        tabs = page.find_tables(clip=clip_rect)
                        if tabs and tabs.tables:
                            for tab in tabs.tables:
                                extracted_rows = tab.extract()
                                if extracted_rows:
                                    headers = tuple(str(h or "") for h in extracted_rows[0])
                                    data_rows = tuple(tuple(val for val in row) for row in extracted_rows[1:])
                                    t_obj = TableData(
                                        name=f"Page_{page_num}_Table_{t_idx}",
                                        headers=headers,
                                        rows=data_rows,
                                    )
                                    page_tables.append(t_obj)
                                    all_doc_tables.append(t_obj)
                    except Exception:
                        pass

            # Fallback table extraction if GNN didn't find any or find_tables in clip yielded none
            if not page_tables:
                try:
                    tabs = page.find_tables()
                    if tabs and tabs.tables:
                        for t_idx, tab in enumerate(tabs.tables, 1):
                            extracted_rows = tab.extract()
                            if extracted_rows:
                                headers = tuple(str(h or "") for h in extracted_rows[0])
                                data_rows = tuple(tuple(val for val in row) for row in extracted_rows[1:])
                                t_obj = TableData(
                                    name=f"Page_{page_num}_Table_{t_idx}",
                                    headers=headers,
                                    rows=data_rows,
                                )
                                page_tables.append(t_obj)
                                all_doc_tables.append(t_obj)
                except Exception:
                    pass

            # Synthesize ordered page text with proper line and paragraph spacing
            block_strings: list[str] = []
            for cls_name, lines in item_blocks:
                if skip_header_footer and cls_name in _HEADER_FOOTER_CLASSES:
                    continue
                block_content = "\n".join(lines).strip()
                if block_content:
                    block_strings.append(block_content)

            if block_strings:
                page_text = "\n\n".join(block_strings)
            else:
                raw_fallback = page.get_text("text", flags=_PDF_TEXT_FLAGS).strip()
                page_text = normalize_text_spacing(raw_fallback)

            if page_text:
                full_text_parts.append(page_text)

            pages.append(
                PageData(
                    page_number=page_num,
                    text=page_text,
                    spans=tuple(ordered_spans),
                    tables=tuple(page_tables),
                    metadata={"layout_classes": tuple(sorted(classes_detected))},
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
                        "reader": "pymupdf_layout",
                        "model": "BoxRFDGNN",
                        "page_count": total_pages,
                        "layout_elements_count": len(layout_items),
                        "classes_detected": sorted(classes_detected),
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
