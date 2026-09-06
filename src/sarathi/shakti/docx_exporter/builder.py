"""OpenXML low-level element serialization and full-document DOCX payload packaging."""

from __future__ import annotations

import io
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


def _format_run_xml(
    text: str,
    font: str,
    size_half_pt: int,
    bold: bool = False,
    italic: bool = False,
    shadow: bool = False,
) -> str:
    """Format an OpenXML <w:r> run string."""
    props: list[str] = [
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>',
        f'<w:sz w:val="{size_half_pt}"/>',
        f'<w:szCs w:val="{size_half_pt}"/>',
    ]
    if bold:
        props.append("<w:b/><w:bCs/>")
    if italic:
        props.append("<w:i/><w:iCs/>")
    if shadow:
        props.append("<w:shadow/>")

    escaped_text = escape(text)
    return (
        f'<w:r><w:rPr>{"".join(props)}</w:rPr>'
        f'<w:t xml:space="preserve">{escaped_text}</w:t></w:r>'
    )


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
        # Unicode -> Legacy mixed output: separate Devanagari legacy runs from Latin/number TNR runs
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
        # General Unicode DOCX policy:
        # English-only -> Times New Roman
        # Hindi-only or Hindi-English mixed -> Nirmala UI (unified run per §18)
        if default_font:
            font = default_font
        else:
            has_devanagari = bool(_DEVANAGARI_CHAR_RE.search(text))
            font = _HINDI_FONT if has_devanagari else _ENGLISH_FONT

        runs = [
            _format_run_xml(
                text,
                font=font,
                size_half_pt=size_half_pt,
                bold=bold,
                italic=italic,
                shadow=shadow,
            )
        ]

    return f'<w:p>{p_pr}{"".join(runs)}</w:p>'


def _format_table_xml(
    table: TableData,
    default_font: str | None = None,
    default_size_pt: float | None = None,
    legacy_target_font: str | None = None,
) -> str:
    """Format a TableData model into an OpenXML <w:tbl> table."""
    parts = [
        '<w:tbl>',
        '<w:tblPr>',
        '<w:tblW w:w="0" w:type="auto"/>',
        '<w:tblBorders>',
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="CCCCCC"/>',
        '</w:tblBorders>',
        '<w:jc w:val="center"/>',
        '</w:tblPr>',
    ]

    # Header Row
    if table.headers:
        parts.append('<w:tr><w:trPr><w:tblHeader/></w:trPr>')
        for h in table.headers:
            h_text = str(h)
            p_xml = _format_paragraph_xml(
                h_text,
                bold=True,
                alignment="center",
                default_font=default_font,
                default_size_pt=default_size_pt,
                legacy_target_font=legacy_target_font,
            )
            parts.append(
                f'<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/></w:tcPr>{p_xml}</w:tc>'
            )
        parts.append('</w:tr>')

    # Data Rows
    for row in table.rows:
        parts.append('<w:tr>')
        for cell in row:
            c_text = str(cell)
            p_xml = _format_paragraph_xml(
                c_text,
                bold=False,
                default_font=default_font,
                default_size_pt=default_size_pt,
                legacy_target_font=legacy_target_font,
            )
            parts.append(f'<w:tc>{p_xml}</w:tc>')
        parts.append('</w:tr>')

    parts.append('</w:tbl>')
    return "".join(parts)


def build_docx_payload(
    doc: CanonicalDocument,
    filename: str,
    role: str = "document_docx",
    header_text: str | None = None,
    default_font: str | None = None,
    default_size_pt: float | None = None,
    legacy_target_font: str | None = None,
) -> ArtifactPayload:
    """Generate a clean, standard OpenXML DOCX ArtifactPayload from a CanonicalDocument.

    Applies the standardized bilingual typography:
    - Hindi: Nirmala UI, 12 pt baseline
    - English: Times New Roman, 12 pt baseline
    - Tables and headers preserved.
    """
    body_parts: list[str] = []

    # Optional Title / Header
    eff_header = header_text or (
        str(doc.metadata.get("header") or doc.metadata.get("title") or "")
        if doc.metadata
        else ""
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
            if p.text:
                for line in p.text.splitlines():
                    trimmed = line.strip()
                    if trimmed:
                        line_bold = False
                        line_size = default_size_pt
                        clean_line = trimmed
                        if trimmed.startswith("# "):
                            clean_line = trimmed[2:].strip()
                            line_bold = True
                            line_size = 16.0
                        elif trimmed.startswith("## "):
                            clean_line = trimmed[3:].strip()
                            line_bold = True
                            line_size = 14.0
                        elif trimmed.startswith("### "):
                            clean_line = trimmed[4:].strip()
                            line_bold = True
                            line_size = 13.0

                        body_parts.append(
                            _format_paragraph_xml(
                                clean_line,
                                bold=line_bold,
                                default_font=default_font,
                                default_size_pt=line_size,
                                legacy_target_font=legacy_target_font,
                            )
                        )
                    else:
                        body_parts.append("<w:p/>")
            if p.tables:
                for tbl in p.tables:
                    rendered_table_ids.add(id(tbl))
                    if tbl.name:
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
        for line in doc.text.splitlines():
            trimmed = line.strip()
            if trimmed:
                line_bold = False
                line_size = default_size_pt
                clean_line = trimmed
                if trimmed.startswith("# "):
                    clean_line = trimmed[2:].strip()
                    line_bold = True
                    line_size = 16.0
                elif trimmed.startswith("## "):
                    clean_line = trimmed[3:].strip()
                    line_bold = True
                    line_size = 14.0
                elif trimmed.startswith("### "):
                    clean_line = trimmed[4:].strip()
                    line_bold = True
                    line_size = 13.0

                body_parts.append(
                    _format_paragraph_xml(
                        clean_line,
                        bold=line_bold,
                        default_font=default_font,
                        default_size_pt=line_size,
                        legacy_target_font=legacy_target_font,
                    )
                )
            else:
                body_parts.append("<w:p/>")

    # Document-level tables (only if not already rendered inside pages)
    if doc.tables:
        for tbl in doc.tables:
            if id(tbl) not in rendered_table_ids:
                if any(
                    tbl.name == pt.name and tbl.headers == pt.headers and tbl.rows == pt.rows
                    for p in (doc.pages or ())
                    for pt in p.tables
                ):
                    continue
                if tbl.name:
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

    # Section properties
    body_parts.append(
        '<w:sectPr>'
        '<w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>'
        '</w:sectPr>'
    )

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">\n'
        f'<w:body>{"".join(body_parts)}</w:body>\n'
        '</w:document>'
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
        '  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>\n'
        '</Types>'
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
        '</Relationships>'
    )

    doc_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>\n'
        '</Relationships>'
    )

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:docDefaults>\n'
        '    <w:rPrDefault>\n'
        f'      <w:rPr><w:rFonts w:ascii="{_ENGLISH_FONT}" w:hAnsi="{_ENGLISH_FONT}" w:cs="{_HINDI_FONT}"/>'
        f'<w:sz w:val="{_DEFAULT_HALF_PT}"/><w:szCs w:val="{_DEFAULT_HALF_PT}"/></w:rPr>\n'
        '    </w:rPrDefault>\n'
        '  </w:docDefaults>\n'
        '</w:styles>'
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
