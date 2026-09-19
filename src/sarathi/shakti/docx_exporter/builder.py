"""OpenXML low-level element serialization and full-document DOCX payload packaging."""

from __future__ import annotations

import io
import math
import re
import zipfile
from xml.sax.saxutils import escape

from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    TableData,
)
from sarathi.shakti.docx_exporter.constants import (
    _DEFAULT_HALF_PT,
    _DEVANAGARI_CHAR_RE,
    _DOCX_MIME_TYPE,
    _ENGLISH_FONT,
    _HINDI_FONT,
)
from sarathi.shakti.docx_exporter.scripts import segment_text_by_script
from sarathi.shakti.text import cell_text


def _format_run_xml(
    text: str,
    font: str,
    size_half_pt: int,
    bold: bool = False,
    italic: bool = False,
    shadow: bool = False,
    *,
    cs_font: str | None = None,
    size_cs_half_pt: int | None = None,
) -> str:
    """Format an OpenXML <w:r> run string with dual-channel font support."""
    eff_cs_font = cs_font or font
    eff_cs_size = size_cs_half_pt if size_cs_half_pt is not None else size_half_pt
    props: list[str] = [
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{eff_cs_font}"/>',
        f'<w:sz w:val="{size_half_pt}"/>',
        f'<w:szCs w:val="{eff_cs_size}"/>',
    ]
    if bold:
        props.append("<w:b/><w:bCs/>")
    if italic:
        props.append("<w:i/><w:iCs/>")
    if shadow:
        props.append("<w:shadow/>")

    escaped_text = escape(text)
    return f'<w:r><w:rPr>{"".join(props)}</w:rPr><w:t xml:space="preserve">{escaped_text}</w:t></w:r>'


def _format_paragraph_xml(
    text: str,
    bold: bool = False,
    italic: bool = False,
    shadow: bool = False,
    alignment: str | None = None,
    default_font: str | None = None,
    default_size_pt: float | None = None,
    legacy_target_font: str | None = None,
) -> str:
    """Format an OpenXML <w:p> paragraph adhering to canonical Sarathi typography policy."""
    p_pr = ""
    if alignment in ("center", "right", "both", "left"):
        p_pr = f'<w:pPr><w:jc w:val="{alignment}"/></w:pPr>'

    if not text:
        return f"<w:p>{p_pr}</w:p>"

    size_half_pt = int(default_size_pt * 2) if default_size_pt and default_size_pt > 0 else _DEFAULT_HALF_PT

    if legacy_target_font:
        has_devanagari = bool(_DEVANAGARI_CHAR_RE.search(text))
        if has_devanagari:
            # Unconverted Unicode Devanagari mixed text: separate Devanagari runs from Latin/number runs
            segments = segment_text_by_script(text)
            runs = [
                _format_run_xml(
                    chunk,
                    font=legacy_target_font if is_dev else _ENGLISH_FONT,
                    size_half_pt=size_half_pt,
                    bold=bold,
                    italic=italic,
                    shadow=shadow,
                )
                for chunk, is_dev in segments
            ]
        else:
            # Converted legacy output: characters reside in Latin-1 code points (e.g. 'Hkkjr' for 'भारत').
            # Assign legacy_target_font directly so MS Word displays Hindi glyphs instead of Latin encoding characters.
            runs = [
                _format_run_xml(
                    text,
                    font=legacy_target_font,
                    size_half_pt=size_half_pt,
                    bold=bold,
                    italic=italic,
                    shadow=shadow,
                )
            ]
    else:
        # General Unicode DOCX policy:
        # English-only -> Times New Roman with Nirmala UI complex script fallback
        # Hindi-only or Hindi-English mixed -> Nirmala UI (unified run per §18)
        has_devanagari = bool(_DEVANAGARI_CHAR_RE.search(text))
        if default_font:
            font = default_font
            cs_font = default_font
        else:
            font = _HINDI_FONT if has_devanagari else _ENGLISH_FONT
            cs_font = _HINDI_FONT

        runs = [
            _format_run_xml(
                text,
                font=font,
                size_half_pt=size_half_pt,
                bold=bold,
                italic=italic,
                shadow=shadow,
                cs_font=cs_font,
            )
        ]

    return f"<w:p>{p_pr}{''.join(runs)}</w:p>"


_TABLE_ANCHOR_RE = re.compile(
    r"^(?:\{\{TABLE:(.+?)\}\}|<!--\s*TABLE:(.+?)\s*-->|\[TABLE:(.+?)\])$",
    re.IGNORECASE,
)


def _calculate_proportional_column_widths(
    table: TableData,
    num_cols: int,
    total_width_dxa: int = 9360,
) -> list[int]:
    """Calculate proportional column widths based on maximum text length across headers and rows."""
    if num_cols <= 0:
        return []
    if num_cols == 1:
        return [total_width_dxa]

    # Calculate content weight for each column based on text length
    col_scores: list[float] = [5.0] * num_cols
    for c_idx in range(num_cols):
        if c_idx < len(table.headers):
            h_len = len(cell_text(table.headers[c_idx]))
            col_scores[c_idx] = max(col_scores[c_idx], float(h_len))
        for row in table.rows:
            if c_idx < len(row):
                cell_str = cell_text(row[c_idx])
                max_line_len = max((len(line) for line in cell_str.splitlines()), default=0)
                col_scores[c_idx] = max(col_scores[c_idx], float(max_line_len))

    # Apply square root damping so long columns don't excessively starve smaller columns
    damped_scores = [max(1.0, math.sqrt(score)) for score in col_scores]
    total_score = sum(damped_scores) or 1.0

    min_w = max(600, min(1440, total_width_dxa // (num_cols * 3)))
    raw_widths = [int(total_width_dxa * (s / total_score)) for s in damped_scores]
    clamped_widths = [max(min_w, w) for w in raw_widths]

    clamped_sum = sum(clamped_widths) or 1
    final_widths = [int(total_width_dxa * (w / clamped_sum)) for w in clamped_widths]

    delta = total_width_dxa - sum(final_widths)
    if delta != 0 and final_widths:
        widest_idx = final_widths.index(max(final_widths))
        final_widths[widest_idx] += delta

    return final_widths


def _format_cell_content_xml(
    cell_text: str,
    bold: bool = False,
    alignment: str | None = None,
    default_font: str | None = None,
    default_size_pt: float | None = None,
    legacy_target_font: str | None = None,
) -> str:
    """Format cell content into one or more paragraphs, preserving multiline cell text."""
    if not cell_text:
        return "<w:p/>"
    lines = [line.strip() for line in cell_text.splitlines() if line.strip()]
    if not lines:
        return "<w:p/>"
    p_elements: list[str] = []
    for line in lines:
        p_elements.append(
            _format_paragraph_xml(
                line,
                bold=bold,
                alignment=alignment,
                default_font=default_font,
                default_size_pt=default_size_pt,
                legacy_target_font=legacy_target_font,
            )
        )
    return "".join(p_elements)


def _format_table_xml(
    table: TableData,
    default_font: str | None = None,
    default_size_pt: float | None = None,
    legacy_target_font: str | None = None,
    total_width_dxa: int = 9360,
) -> str:
    """Format a TableData model into an OpenXML <w:tbl> table with proportional grid columns and cell margins."""
    num_cols = len(table.headers)
    if table.rows:
        num_cols = max(num_cols, max((len(r) for r in table.rows), default=0))

    if num_cols <= 0:
        return ""

    col_widths = _calculate_proportional_column_widths(table, num_cols, total_width_dxa=total_width_dxa)
    grid_cols = "".join(f'<w:gridCol w:w="{w}"/>' for w in col_widths)

    parts = [
        "<w:tbl>",
        "<w:tblPr>",
        f'<w:tblW w:w="{total_width_dxa}" w:type="dxa"/>',
        '<w:jc w:val="center"/>',
        "<w:tblBorders>",
        '<w:top w:val="single" w:sz="6" w:space="0" w:color="D3D3D3"/>',
        '<w:left w:val="single" w:sz="6" w:space="0" w:color="D3D3D3"/>',
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="D3D3D3"/>',
        '<w:right w:val="single" w:sz="6" w:space="0" w:color="D3D3D3"/>',
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="E5E7EB"/>',
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="E5E7EB"/>',
        "</w:tblBorders>",
        "<w:tblCellMar>",
        '<w:top w:w="120" w:type="dxa"/>',
        '<w:left w:w="160" w:type="dxa"/>',
        '<w:bottom w:w="120" w:type="dxa"/>',
        '<w:right w:w="160" w:type="dxa"/>',
        "</w:tblCellMar>",
        "</w:tblPr>",
        f"<w:tblGrid>{grid_cols}</w:tblGrid>",
    ]

    # Standard table typography: 11.0 pt standard, 10.0 pt for dense tables (>= 6 columns)
    base_tbl_size_pt = 10.0 if num_cols >= 6 else 11.0
    eff_tbl_size_pt = default_size_pt if (default_size_pt is not None and default_size_pt < 12.0) else base_tbl_size_pt

    # Header Row
    if table.headers:
        parts.append("<w:tr><w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>")
        for c_idx in range(num_cols):
            h_text = cell_text(table.headers[c_idx]) if c_idx < len(table.headers) else ""
            c_w = col_widths[c_idx]
            p_xml = _format_cell_content_xml(
                h_text,
                bold=True,
                alignment="center",
                default_font=default_font,
                default_size_pt=eff_tbl_size_pt,
                legacy_target_font=legacy_target_font,
            )
            parts.append(
                f"<w:tc><w:tcPr>"
                f'<w:tcW w:w="{c_w}" w:type="dxa"/>'
                f'<w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>'
                f'<w:vAlign w:val="center"/>'
                f"</w:tcPr>{p_xml}</w:tc>"
            )
        parts.append("</w:tr>")

    # Data Rows
    for row in table.rows:
        parts.append("<w:tr><w:trPr><w:cantSplit/></w:trPr>")
        for c_idx in range(num_cols):
            cell_val = cell_text(row[c_idx]) if c_idx < len(row) else ""
            c_w = col_widths[c_idx]
            p_xml = _format_cell_content_xml(
                cell_val,
                bold=False,
                default_font=default_font,
                default_size_pt=eff_tbl_size_pt,
                legacy_target_font=legacy_target_font,
            )
            parts.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{c_w}" w:type="dxa"/><w:vAlign w:val="top"/></w:tcPr>{p_xml}</w:tc>'
            )
        parts.append("</w:tr>")

    parts.append("</w:tbl>")
    return "".join(parts)


def build_docx_payload(
    doc: CanonicalDocument,
    filename: str,
    role: str = "document_docx",
    header_text: str | None = None,
    default_font: str | None = None,
    default_size_pt: float | None = None,
    legacy_target_font: str | None = None,
    interpret_markdown_headings: bool = True,
) -> ArtifactPayload:
    """Generate a clean, standard OpenXML DOCX ArtifactPayload from a CanonicalDocument.

    Applies the standardized bilingual typography:
    - Hindi: Nirmala UI, 12 pt baseline
    - English: Times New Roman, 12 pt baseline
    - Tables and headers preserved with proportional column layout.
    """
    body_parts: list[str] = []

    # Optional Title / Header
    eff_header = header_text or (
        str(doc.metadata.get("header") or doc.metadata.get("title") or "") if doc.metadata else ""
    )
    if eff_header.strip():
        body_parts.append(
            _format_paragraph_xml(
                eff_header.strip(),
                bold=True,
                alignment="center",
                default_font=default_font,
                default_size_pt=default_size_pt,
                legacy_target_font=legacy_target_font,
            )
        )

    rendered_table_ids: set[int] = set()
    rendered_table_names: set[str] = set()

    # Paragraphs or page text
    if doc.pages:
        for p in doc.pages:
            if len(doc.pages) > 1:
                body_parts.append(
                    _format_paragraph_xml(
                        f"--- Page {p.page_number} ---",
                        bold=True,
                        alignment="center",
                        default_font=default_font,
                        default_size_pt=default_size_pt,
                        legacy_target_font=legacy_target_font,
                    )
                )

            # Build row signatures and lookup table for current page
            table_row_signatures: set[str] = set()
            page_tables_by_name: dict[str, TableData] = {}
            if p.tables:
                for t_idx, tbl in enumerate(p.tables, 1):
                    if tbl.name:
                        page_tables_by_name[tbl.name.strip().lower()] = tbl
                    page_tables_by_name[f"table_{t_idx}"] = tbl
                    page_tables_by_name[f"table {t_idx}"] = tbl
                    if tbl.headers:
                        table_row_signatures.add(" | ".join(cell_text(c) for c in tbl.headers))
                        table_row_signatures.add("\t".join(cell_text(c) for c in tbl.headers))
                    for row in tbl.rows:
                        table_row_signatures.add(" | ".join(cell_text(c) for c in row))
                        table_row_signatures.add("\t".join(cell_text(c) for c in row))

            if p.text:
                for line in p.text.splitlines():
                    trimmed = line.strip()
                    if not trimmed:
                        body_parts.append("<w:p/>")
                        continue

                    # 1. Check for in-flow table anchor
                    m = _TABLE_ANCHOR_RE.match(trimmed)
                    if m:
                        anchor_name = (m.group(1) or m.group(2) or m.group(3)).strip().lower()
                        tbl = page_tables_by_name.get(anchor_name)
                        if tbl is None and doc.tables:
                            tbl = next(
                                (t for t in doc.tables if t.name and t.name.strip().lower() == anchor_name),
                                None,
                            )
                        if tbl is not None and id(tbl) not in rendered_table_ids:
                            rendered_table_ids.add(id(tbl))
                            if tbl.name:
                                rendered_table_names.add(tbl.name.strip().lower())
                            if tbl.name and not tbl.name.startswith("Table_") and not tbl.name.startswith("Page_"):
                                body_parts.append(
                                    _format_paragraph_xml(
                                        tbl.name,
                                        bold=True,
                                        default_font=default_font,
                                        default_size_pt=default_size_pt,
                                        legacy_target_font=legacy_target_font,
                                    )
                                )
                            body_parts.append(
                                _format_table_xml(
                                    tbl,
                                    default_font=default_font,
                                    default_size_pt=default_size_pt,
                                    legacy_target_font=legacy_target_font,
                                )
                            )
                            body_parts.append("<w:p/>")
                            continue

                    # 2. Suppress duplicate plain-text table rows
                    if trimmed in table_row_signatures:
                        continue

                    line_bold = False
                    line_size = default_size_pt
                    clean_line = trimmed
                    if interpret_markdown_headings:
                        if trimmed.startswith("# "):
                            cand = trimmed[2:].strip()
                            if cand and not cand.endswith((".", "।", ";", ",", ":")) and len(cand.split()) <= 12:
                                clean_line = cand
                                line_bold = True
                                line_size = 16.0
                        elif trimmed.startswith("## "):
                            cand = trimmed[3:].strip()
                            if cand and not cand.endswith((".", "।", ";", ",", ":")) and len(cand.split()) <= 12:
                                clean_line = cand
                                line_bold = True
                                line_size = 14.0
                        elif trimmed.startswith("### "):
                            cand = trimmed[4:].strip()
                            if cand and not cand.endswith((".", "।", ";", ",", ":")) and len(cand.split()) <= 12:
                                clean_line = cand
                                line_bold = True
                                line_size = 13.0
                    else:
                        if trimmed.startswith("### "):
                            clean_line = trimmed[4:].strip()
                            line_bold = True
                        elif trimmed.startswith("## "):
                            clean_line = trimmed[3:].strip()
                            line_bold = True
                        elif trimmed.startswith("# "):
                            clean_line = trimmed[2:].strip()
                            line_bold = True

                    body_parts.append(
                        _format_paragraph_xml(
                            clean_line,
                            bold=line_bold,
                            default_font=default_font,
                            default_size_pt=line_size,
                            legacy_target_font=legacy_target_font,
                        )
                    )

            # Unanchored tables on current page rendered at natural bottom of page
            if p.tables:
                for tbl in p.tables:
                    if id(tbl) not in rendered_table_ids:
                        rendered_table_ids.add(id(tbl))
                        if tbl.name and not tbl.name.startswith("Page_") and not tbl.name.startswith("Table_"):
                            body_parts.append(
                                _format_paragraph_xml(
                                    tbl.name,
                                    bold=True,
                                    default_font=default_font,
                                    default_size_pt=default_size_pt,
                                    legacy_target_font=legacy_target_font,
                                )
                            )
                        body_parts.append(
                            _format_table_xml(
                                tbl,
                                default_font=default_font,
                                default_size_pt=default_size_pt,
                                legacy_target_font=legacy_target_font,
                            )
                        )
                        body_parts.append("<w:p/>")

    elif doc.text:
        table_row_signatures = set()
        doc_tables_by_name = {}
        if doc.tables:
            for t_idx, tbl in enumerate(doc.tables, 1):
                if tbl.name:
                    doc_tables_by_name[tbl.name.strip().lower()] = tbl
                doc_tables_by_name[f"table_{t_idx}"] = tbl
                doc_tables_by_name[f"table {t_idx}"] = tbl
                if tbl.headers:
                    table_row_signatures.add(" | ".join(cell_text(c) for c in tbl.headers))
                    table_row_signatures.add("\t".join(cell_text(c) for c in tbl.headers))
                for row in tbl.rows:
                    table_row_signatures.add(" | ".join(cell_text(c) for c in row))
                    table_row_signatures.add("\t".join(cell_text(c) for c in row))

        for line in doc.text.splitlines():
            trimmed = line.strip()
            if not trimmed:
                body_parts.append("<w:p/>")
                continue

            # 1. Check for in-flow table anchor
            m = _TABLE_ANCHOR_RE.match(trimmed)
            if m:
                anchor_name = (m.group(1) or m.group(2) or m.group(3)).strip().lower()
                tbl = doc_tables_by_name.get(anchor_name)
                if tbl is not None and id(tbl) not in rendered_table_ids:
                    rendered_table_ids.add(id(tbl))
                    if tbl.name:
                        rendered_table_names.add(tbl.name.strip().lower())
                    if tbl.name and not tbl.name.startswith("Table_") and not tbl.name.startswith("Page_"):
                        body_parts.append(
                            _format_paragraph_xml(
                                tbl.name,
                                bold=True,
                                default_font=default_font,
                                default_size_pt=default_size_pt,
                                legacy_target_font=legacy_target_font,
                            )
                        )
                    body_parts.append(
                        _format_table_xml(
                            tbl,
                            default_font=default_font,
                            default_size_pt=default_size_pt,
                            legacy_target_font=legacy_target_font,
                        )
                    )
                    body_parts.append("<w:p/>")
                    continue

            # 2. Suppress duplicate plain-text table rows
            if trimmed in table_row_signatures:
                continue

            line_bold = False
            line_size = default_size_pt
            clean_line = trimmed
            if interpret_markdown_headings:
                if trimmed.startswith("# "):
                    cand = trimmed[2:].strip()
                    if cand and not cand.endswith((".", "।", ";", ",", ":")) and len(cand.split()) <= 12:
                        clean_line = cand
                        line_bold = True
                        line_size = 16.0
                elif trimmed.startswith("## "):
                    cand = trimmed[3:].strip()
                    if cand and not cand.endswith((".", "।", ";", ",", ":")) and len(cand.split()) <= 12:
                        clean_line = cand
                        line_bold = True
                        line_size = 14.0
                elif trimmed.startswith("### "):
                    cand = trimmed[4:].strip()
                    if cand and not cand.endswith((".", "।", ";", ",", ":")) and len(cand.split()) <= 12:
                        clean_line = cand
                        line_bold = True
                        line_size = 13.0
            else:
                if trimmed.startswith("### "):
                    clean_line = trimmed[4:].strip()
                    line_bold = True
                elif trimmed.startswith("## "):
                    clean_line = trimmed[3:].strip()
                    line_bold = True
                elif trimmed.startswith("# "):
                    clean_line = trimmed[2:].strip()
                    line_bold = True

            body_parts.append(
                _format_paragraph_xml(
                    clean_line,
                    bold=line_bold,
                    default_font=default_font,
                    default_size_pt=line_size,
                    legacy_target_font=legacy_target_font,
                )
            )

    # Document-level tables (only if not already rendered inside pages or text)
    if doc.tables:
        for tbl in doc.tables:
            norm_name = tbl.name.strip().lower() if tbl.name else ""
            if id(tbl) not in rendered_table_ids and (not norm_name or norm_name not in rendered_table_names):
                if any(tbl.headers == pt.headers and tbl.rows == pt.rows for p in (doc.pages or ()) for pt in p.tables):
                    continue
                rendered_table_ids.add(id(tbl))
                if norm_name:
                    rendered_table_names.add(norm_name)
                if tbl.name and not tbl.name.startswith("Page_") and not tbl.name.startswith("Table_"):
                    body_parts.append(
                        _format_paragraph_xml(
                            tbl.name,
                            bold=True,
                            default_font=default_font,
                            default_size_pt=default_size_pt,
                            legacy_target_font=legacy_target_font,
                        )
                    )
                body_parts.append(
                    _format_table_xml(
                        tbl,
                        default_font=default_font,
                        default_size_pt=default_size_pt,
                        legacy_target_font=legacy_target_font,
                    )
                )
                body_parts.append("<w:p/>")

    # Multi-column section styling
    # Invariant: a document should only use multi-column section styling if an overwhelming
    # majority (>= 75%) of pages are multi-column, or if explicitly declared in doc.metadata.
    # Isolated multi-column pages in a multi-page document must not corrupt the document layout.
    col_count = 1
    if doc.pages:
        multi_pages = sum(
            1 for p in doc.pages if isinstance(p.metadata.get("column_count"), int) and p.metadata["column_count"] >= 2
        )
        if len(doc.pages) == 1:
            col_count = doc.pages[0].metadata.get("column_count", 1)
        elif multi_pages >= 0.75 * len(doc.pages):
            col_count = 2
    elif doc.metadata:
        c = doc.metadata.get("column_count", 1)
        if isinstance(c, int) and c >= 2:
            col_count = c
    if not isinstance(col_count, int) or col_count < 1:
        col_count = 1

    cols_xml = f'<w:cols w:num="{col_count}" w:space="720"/>' if col_count >= 2 else '<w:cols w:space="720"/>'

    # Section properties
    body_parts.append(
        "<w:sectPr>"
        '<w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        f"{cols_xml}"
        "</w:sectPr>"
    )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        f"<w:body>{''.join(body_parts)}</w:body>\n"
        "</w:document>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n'
        "</Types>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        "</Relationships>"
    )

    doc_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>\n'
        "</Relationships>"
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        "  <w:docDefaults>\n"
        "    <w:rPrDefault>\n"
        f'      <w:rPr><w:rFonts w:ascii="{_ENGLISH_FONT}" w:hAnsi="{_ENGLISH_FONT}" w:cs="{_HINDI_FONT}"/>'
        f'<w:sz w:val="{_DEFAULT_HALF_PT}"/><w:szCs w:val="{_DEFAULT_HALF_PT}"/></w:rPr>\n'
        "    </w:rPrDefault>\n"
        "  </w:docDefaults>\n"
        "</w:styles>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/_rels/document.xml.rels", doc_rels_xml)
        zf.writestr("word/styles.xml", styles_xml)
        zf.writestr("word/document.xml", doc_xml)

    return ArtifactPayload(
        intent=ArtifactIntent(name=filename, role=role, media_type=_DOCX_MIME_TYPE),
        content=buf.getvalue(),
    )
