"""DOCX OpenXML document reader extracting paragraphs, rich text spans, and tables."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CanonicalDocument,
    PageData,
    ProvenanceRecord,
    TableData,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.docx_exporter import DocxStyleResolver
from sarathi.shakti.native_extraction.readers.common import (
    CAPABILITY_ID,
    PLUGIN_ID,
    STAGE_NAME,
)

_W_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_P_TAG = f"{_W_NAMESPACE}p"
_R_TAG = f"{_W_NAMESPACE}r"
_T_TAG = f"{_W_NAMESPACE}t"
_TBL_TAG = f"{_W_NAMESPACE}tbl"
_TR_TAG = f"{_W_NAMESPACE}tr"
_TC_TAG = f"{_W_NAMESPACE}tc"


def _extract_docx_cell_text(tc_elem: ET.Element) -> str:
    """Extract nested paragraph or table text from a table cell element."""
    parts: list[str] = []
    for child in tc_elem:
        if child.tag == _P_TAG:
            p_text = "".join(t.text for t in child.findall(f".//{_T_TAG}") if t.text)
            if p_text:
                parts.append(p_text)
        elif child.tag == _TBL_TAG:
            for sub_tr in child.findall(_TR_TAG):
                row_parts: list[str] = []
                for sub_tc in sub_tr.findall(_TC_TAG):
                    sub_text = _extract_docx_cell_text(sub_tc)
                    if sub_text:
                        row_parts.append(sub_text)
                if row_parts:
                    parts.append(" ".join(row_parts))
        elif child.tag == f"{_W_NAMESPACE}sdt":
            sdt_text = "".join(t.text for t in child.findall(f".//{_T_TAG}") if t.text)
            if sdt_text:
                parts.append(sdt_text)
    if not parts:
        return "".join(t.text for t in tc_elem.findall(f".//{_T_TAG}") if t.text).strip()
    return "\n".join(parts).strip()


def read_docx(
    data: bytes,
    input_id: str,
) -> tuple[CanonicalDocument, tuple[ProvenanceRecord, ...], tuple[WarningRecord, ...]]:
    """Extract full text, paragraphs, spans with font evidence, and tables from a DOCX document."""
    tables: list[TableData] = []
    paragraphs: list[str] = []
    spans: list[TextSpan] = []
    provenances: list[ProvenanceRecord] = []
    warnings: list[WarningRecord] = []

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if "word/document.xml" not in zf.namelist():
            raise DoshError(
                code=FailureCode.UNSUPPORTED,
                message="DOCX file is missing required word/document.xml.",
            )
        styles_xml = zf.read("word/styles.xml") if "word/styles.xml" in zf.namelist() else None
        style_resolver = DocxStyleResolver(styles_xml)

        doc_xml = zf.read("word/document.xml")
        tree = ET.fromstring(doc_xml)

        body = tree.find(f"{_W_NAMESPACE}body")
        if body is not None:
            tbl_count = 0
            p_count = 0
            for elem in body:
                if elem.tag == _P_TAG:
                    p_count += 1
                    p_runs_text: list[str] = []
                    run_count = 0
                    for r in elem.findall(_R_TAG):
                        r_text = "".join(t.text for t in r.findall(_T_TAG) if t.text)
                        if r_text:
                            run_count += 1
                            p_runs_text.append(r_text)
                            effective_font = style_resolver.resolve_run_font(
                                r, elem, text=r_text
                            )

                            # Determine font size and heading status
                            eff_half_pt = style_resolver.resolve_run_size_half_pt(r, elem)
                            font_size_pt = round(eff_half_pt / 2.0, 1) if eff_half_pt is not None else None
                            p_style_elem = elem.find(f"{_W_NAMESPACE}pPr/{_W_NAMESPACE}pStyle")
                            p_style = p_style_elem.attrib.get(f"{_W_NAMESPACE}val", "") if p_style_elem is not None else ""
                            is_heading = bool(
                                "heading" in p_style.lower()
                                or "title" in p_style.lower()
                                or (font_size_pt is not None and font_size_pt >= 14.0 and r.find(f"{_W_NAMESPACE}rPr/{_W_NAMESPACE}b") is not None)
                            )

                            # Determine font source
                            font_source = "doc_defaults"
                            rpr = r.find(f"{_W_NAMESPACE}rPr")
                            if rpr is not None:
                                if rpr.find(f"{_W_NAMESPACE}rFonts") is not None:
                                    font_source = "direct_run_property"
                                elif rpr.find(f"{_W_NAMESPACE}rStyle") is not None:
                                    font_source = "character_style"
                            elif elem.find(f"{_W_NAMESPACE}pPr/{_W_NAMESPACE}pStyle") is not None:
                                font_source = "paragraph_style"

                            spans.append(
                                TextSpan(
                                    text=r_text,
                                    metadata={
                                        "font_name": effective_font or "",
                                        "font_source": font_source,
                                        "font_size_pt": font_size_pt,
                                        "is_heading": is_heading,
                                        "run_index": run_count,
                                        "paragraph_index": p_count,
                                        "document_part": "document",
                                    },
                                )
                            )
                    p_text = "".join(p_runs_text).strip()
                    if p_text:
                        paragraphs.append(p_text)
                elif elem.tag == _TBL_TAG:
                    tbl_count += 1
                    raw_table_rows: list[tuple[str, ...]] = []
                    cell_fonts: list[list[str]] = []
                    for tr in elem.findall(_TR_TAG):
                        row_cells: list[str] = []
                        row_font_list: list[str] = []
                        for tc in tr.findall(_TC_TAG):
                            tc_text = _extract_docx_cell_text(tc)
                            row_cells.append(tc_text)
                            first_r = tc.find(f".//{_R_TAG}")
                            first_p = tc.find(f".//{_P_TAG}")
                            c_font = ""
                            if first_r is not None:
                                has_cs = any("\u0900" <= c <= "\u0d7f" for c in tc_text)
                                c_font = style_resolver.resolve_run_font(
                                    first_r, first_p, is_ascii_text=not has_cs
                                ) or ""
                            row_font_list.append(c_font)
                        if any(row_cells):
                            raw_table_rows.append(tuple(row_cells))
                            cell_fonts.append(row_font_list)

                    if raw_table_rows:
                        headers = raw_table_rows[0]
                        data_rows = tuple(raw_table_rows[1:])
                        tables.append(
                            TableData(
                                name=f"Table_{tbl_count}",
                                headers=headers,
                                rows=data_rows,
                                metadata={"cell_fonts": cell_fonts},
                            )
                        )
                        for r_row in raw_table_rows:
                            paragraphs.append(" | ".join(r_row))

    provenances.append(
        ProvenanceRecord(
            source_input_id=input_id,
            stage=STAGE_NAME,
            plugin_id=PLUGIN_ID,
            capability_id=CAPABILITY_ID,
            evidence={
                "reader": "docx_openxml",
                "paragraph_count": len(paragraphs),
                "span_count": len(spans),
                "table_count": len(tables),
            },
        )
    )

    full_text = "\n".join(paragraphs)
    page = PageData(
        page_number=1,
        text=full_text,
        spans=tuple(spans),
        tables=tuple(tables),
    )
    canonical_doc = CanonicalDocument(
        document_id=f"doc-{input_id}",
        source_input_id=input_id,
        text=full_text,
        pages=(page,),
        tables=tuple(tables),
        detected_type="docx",
        metadata={"reader": "docx_openxml"},
    )
    return canonical_doc, tuple(provenances), tuple(warnings)
