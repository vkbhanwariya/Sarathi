"""Canonical OpenXML DOCX Document Exporter and Transformer for Sarathi Shakti.

Provides standardized bilingual document export and in-place DOCX transformation:
- Hindi (Devanagari): Nirmala UI, 14 pt (w:sz=28)
- English / Latin: Arial, 12 pt (w:sz=24)
- Preserves bold, italic, shadow, alignment, tables, and headers.
"""

from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable
from typing import Any
from xml.sax.saxutils import escape

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    TableData,
    WarningRecord,
)

# OpenXML Namespaces
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

ET.register_namespace("w", _W_NS)
ET.register_namespace("r", _R_NS)

# Devanagari Unicode Blocks: standard Devanagari, Vedic Extensions, Devanagari Extended
_DEVANAGARI_CHAR_RE = re.compile(r"[\u0900-\u097F\u1CD0-\u1CFF\uA8E0-\uA8FF]")

# Typography constants per user specification
_HINDI_FONT = "Nirmala UI"
_HINDI_HALF_PT = 28  # 14 pt
_ENGLISH_FONT = "Arial"
_ENGLISH_HALF_PT = 24  # 12 pt

_DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def segment_text_by_script(text: str) -> list[tuple[str, bool]]:
    """Segment text into contiguous chunks with a flag indicating whether it is Devanagari.

    Returns:
        list of tuples (chunk_text, is_devanagari).
    """
    if not text:
        return []

    chunks: list[tuple[str, bool]] = []
    current_chars: list[str] = []
    current_is_dev: bool | None = None

    for char in text:
        is_dev = bool(_DEVANAGARI_CHAR_RE.match(char))
        # Keep neutral whitespace/punctuation with current active script if set
        if char.isspace() or unicodedata.category(char).startswith("P"):
            if current_is_dev is None:
                current_is_dev = False
            current_chars.append(char)
            continue

        if current_is_dev is None:
            current_is_dev = is_dev
            current_chars.append(char)
        elif is_dev == current_is_dev:
            current_chars.append(char)
        else:
            if current_chars:
                chunks.append(("".join(current_chars), current_is_dev))
            current_chars = [char]
            current_is_dev = is_dev

    if current_chars:
        chunks.append(("".join(current_chars), current_is_dev if current_is_dev is not None else False))

    return chunks


def _format_run_xml(
    text: str,
    is_devanagari: bool,
    bold: bool = False,
    italic: bool = False,
    shadow: bool = False,
) -> str:
    """Format an OpenXML <w:r> run string."""
    font = _HINDI_FONT if is_devanagari else _ENGLISH_FONT
    size = _HINDI_HALF_PT if is_devanagari else _ENGLISH_HALF_PT

    props: list[str] = [
        f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>',
        f'<w:sz w:val="{size}"/>',
        f'<w:szCs w:val="{size}"/>',
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
) -> str:
    """Format an OpenXML <w:p> paragraph with script-segmented runs."""
    p_pr = ""
    if alignment in ("center", "right", "both", "left"):
        p_pr = f"<w:pPr><w:jc w:val=\"{alignment}\"/></w:pPr>"

    if not text:
        return f"<w:p>{p_pr}</w:p>"

    segments = segment_text_by_script(text)
    runs = [
        _format_run_xml(chunk, is_dev, bold=bold, italic=italic, shadow=shadow)
        for chunk, is_dev in segments
    ]
    return f'<w:p>{p_pr}{"".join(runs)}</w:p>'


def _format_table_xml(table: TableData) -> str:
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
            p_xml = _format_paragraph_xml(h_text, bold=True, alignment="center")
            parts.append(
                f'<w:tc><w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/></w:tcPr>{p_xml}</w:tc>'
            )
        parts.append('</w:tr>')

    # Data Rows
    for row in table.rows:
        parts.append('<w:tr>')
        for cell in row:
            c_text = str(cell)
            p_xml = _format_paragraph_xml(c_text, bold=False)
            parts.append(f'<w:tc>{p_xml}</w:tc>')
        parts.append('</w:tr>')

    parts.append('</w:tbl>')
    return "".join(parts)


def build_docx_payload(
    doc: CanonicalDocument,
    filename: str,
    role: str = "document_docx",
    header_text: str | None = None,
) -> ArtifactPayload:
    """Generate a clean, standard OpenXML DOCX ArtifactPayload from a CanonicalDocument.

    Applies the standardized bilingual typography:
    - Hindi: Nirmala UI, 14 pt
    - English: Arial, 12 pt
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
            _format_paragraph_xml(eff_header.strip(), bold=True, alignment="center")
        )

    rendered_table_ids: set[int] = set()

    # Paragraphs or page text
    if doc.pages:
        for p in doc.pages:
            if len(doc.pages) > 1:
                body_parts.append(
                    _format_paragraph_xml(f"--- Page {p.page_number} ---", bold=True, alignment="center")
                )
            if p.text:
                for line in p.text.splitlines():
                    trimmed = line.strip()
                    if trimmed:
                        body_parts.append(_format_paragraph_xml(trimmed))
                    else:
                        body_parts.append("<w:p/>")
            if p.tables:
                for tbl in p.tables:
                    rendered_table_ids.add(id(tbl))
                    if tbl.name:
                        body_parts.append(_format_paragraph_xml(tbl.name, bold=True))
                    body_parts.append(_format_table_xml(tbl))
                    body_parts.append("<w:p/>")
    elif doc.text:
        for line in doc.text.splitlines():
            trimmed = line.strip()
            if trimmed:
                body_parts.append(_format_paragraph_xml(trimmed))
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
                    body_parts.append(_format_paragraph_xml(tbl.name, bold=True))
                body_parts.append(_format_table_xml(tbl))
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
        f'<w:sz w:val="{_ENGLISH_HALF_PT}"/><w:szCs w:val="{_HINDI_HALF_PT}"/></w:rPr>\n'
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


class DocxStyleResolver:
    """Resolves effective OpenXML run fonts through styles and docDefaults hierarchy."""

    def __init__(self, styles_xml: bytes | None = None) -> None:
        self.doc_default_fonts: dict[str, str] = {}
        self.styles: dict[str, dict[str, Any]] = {}
        if styles_xml:
            self._parse_styles(styles_xml)

    def _parse_styles(self, styles_xml: bytes) -> None:
        try:
            root = ET.fromstring(styles_xml)
        except Exception:
            return

        # 1. docDefaults
        rpr_def = root.find(f".//{{{_W_NS}}}docDefaults/{{{_W_NS}}}rPrDefault/{{{_W_NS}}}rPr")
        if rpr_def is not None:
            rf = rpr_def.find(f"{{{_W_NS}}}rFonts")
            if rf is not None:
                for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                    val = rf.attrib.get(f"{{{_W_NS}}}{attr}")
                    if val:
                        self.doc_default_fonts[attr] = val

        # 2. styles
        for s in root.findall(f"{{{_W_NS}}}style"):
            style_id = s.attrib.get(f"{{{_W_NS}}}styleId")
            if not style_id:
                continue
            style_type = s.attrib.get(f"{{{_W_NS}}}type", "paragraph")
            based_on = None
            bo_elem = s.find(f"{{{_W_NS}}}basedOn")
            if bo_elem is not None:
                based_on = bo_elem.attrib.get(f"{{{_W_NS}}}val")

            fonts: dict[str, str] = {}
            rpr = s.find(f"{{{_W_NS}}}rPr")
            if rpr is not None:
                rf = rpr.find(f"{{{_W_NS}}}rFonts")
                if rf is not None:
                    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                        val = rf.attrib.get(f"{{{_W_NS}}}{attr}")
                        if val:
                            fonts[attr] = val

            self.styles[style_id] = {
                "type": style_type,
                "based_on": based_on,
                "fonts": fonts,
            }

    def resolve_run_font_channels(
        self,
        r: ET.Element,
        p: ET.Element | None = None,
    ) -> dict[str, str]:
        """Resolve all available font channels (ascii, hAnsi, cs, eastAsia) for run r."""
        channels: dict[str, str] = {}

        # 1. Direct rPr / rFonts
        rpr = r.find(f"{{{_W_NS}}}rPr")
        if rpr is not None:
            rf = rpr.find(f"{{{_W_NS}}}rFonts")
            if rf is not None:
                for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                    val = rf.attrib.get(f"{{{_W_NS}}}{attr}")
                    if val:
                        channels[attr] = val

            # 2. Character style (rStyle)
            rstyle = rpr.find(f"{{{_W_NS}}}rStyle")
            if rstyle is not None:
                sid = rstyle.attrib.get(f"{{{_W_NS}}}val")
                self._fill_channels_from_style(sid, channels)

        # 3. Paragraph style (pStyle)
        if p is not None:
            ppr = p.find(f"{{{_W_NS}}}pPr")
            if ppr is not None:
                pstyle = ppr.find(f"{{{_W_NS}}}pStyle")
                if pstyle is not None:
                    sid = pstyle.attrib.get(f"{{{_W_NS}}}val")
                    self._fill_channels_from_style(sid, channels)

        # 4. Document defaults
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            if attr not in channels and attr in self.doc_default_fonts:
                channels[attr] = self.doc_default_fonts[attr]

        return channels

    def _fill_channels_from_style(self, style_id: str | None, channels: dict[str, str]) -> None:
        visited: set[str] = set()
        curr = style_id
        while curr and curr not in visited:
            visited.add(curr)
            s_info = self.styles.get(curr)
            if not s_info:
                break
            fonts = s_info.get("fonts", {})
            for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
                if attr not in channels and attr in fonts:
                    channels[attr] = fonts[attr]
            curr = s_info.get("based_on")

    def resolve_run_font(
        self,
        r: ET.Element,
        p: ET.Element | None = None,
        is_ascii_text: bool = True,
        text: str | None = None,
    ) -> str | None:
        """Resolve effective font name for run r following the OpenXML hierarchy."""
        channels = self.resolve_run_font_channels(r, p)
        if not channels:
            return None

        if text is not None:
            from sarathi.shakti.font_conversion.detector import resolve_effective_font

            return resolve_effective_font(
                ascii_font=channels.get("ascii"),
                hansi_font=channels.get("hAnsi"),
                cs_font=channels.get("cs"),
                run_text=text,
            )

        if is_ascii_text:
            return channels.get("ascii") or channels.get("hAnsi") or channels.get("cs")
        return channels.get("cs") or channels.get("ascii") or channels.get("hAnsi")


_NON_DELETABLE_RUN_CHILDREN = frozenset({
    "tab", "br", "cr", "sym", "drawing", "fldChar", "instrText",
    "noBreakHyphen", "softHyphen", "commentReference", "annotationRef",
    "footnoteReference", "endnoteReference",
    "lastRenderedPageBreak", "ptab", "ruby",
})


def _serialize_xml_preserving_namespaces(
    tree: ET.Element,
    raw_entry: bytes,
) -> bytes:
    """Serialize an ElementTree root element to bytes, preserving root namespace declarations."""
    # 1. Register all namespace prefixes declared in the source XML
    try:
        for event, (prefix, uri) in ET.iterparse(io.BytesIO(raw_entry), events=["start-ns"]):
            if prefix:
                try:
                    ET.register_namespace(prefix, uri)
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Serialize tree with ElementTree
    serialized = ET.tostring(tree, encoding="utf-8", xml_declaration=True)

    # 3. Extract all xmlns and xmlns:prefix declarations from source root element
    root_match = re.search(rb"<([a-zA-Z0-9_:-]+)\b([^>]*)>", raw_entry)
    if not root_match:
        return serialized

    root_attrs_raw = root_match.group(2).decode("utf-8", errors="ignore")
    source_xmlns = re.findall(r'(xmlns(?::[a-zA-Z0-9_.-]+)?)=["\']([^"\']+)["\']', root_attrs_raw)
    if not source_xmlns:
        return serialized

    # Check which xmlns declarations are present in the serialized root tag
    ser_match = re.search(rb"<([a-zA-Z0-9_:-]+)\b([^>]*)>", serialized)
    if not ser_match:
        return serialized

    ser_attrs_raw = ser_match.group(2).decode("utf-8", errors="ignore")
    existing_xmlns_attrs = set(re.findall(r'(xmlns(?::[a-zA-Z0-9_.-]+)?)=', ser_attrs_raw))

    missing_xmlns = []
    for attr_name, uri in source_xmlns:
        if attr_name not in existing_xmlns_attrs:
            missing_xmlns.append(f'{attr_name}="{uri}"')

    if missing_xmlns:
        injection = (" " + " ".join(missing_xmlns)).encode("utf-8")
        root_end = ser_match.end() - 1
        if serialized[root_end - 1 : root_end] == b"/":
            root_end -= 1
        return serialized[:root_end] + injection + serialized[root_end:]

    return serialized


def transform_docx_artifact(
    input_bytes: bytes,
    converter_fn: Callable[[str], str],
    filename: str,
    role: str = "converted_document",
    warnings: list[WarningRecord] | None = None,
    preserve_modern_fonts: bool | None = None,
    preserve_typography: bool = False,
) -> ArtifactPayload:
    """Transform an existing DOCX file in-place, preserving OpenXML layout and document structure."""
    try:
        in_buf = io.BytesIO(input_bytes)
        out_buf = io.BytesIO()
        should_preserve_modern = preserve_modern_fonts if preserve_modern_fonts is not None else (role == "converted_document")

        with zipfile.ZipFile(in_buf, "r") as in_zf, zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as out_zf:
            styles_xml = in_zf.read("word/styles.xml") if "word/styles.xml" in in_zf.namelist() else None
            style_resolver = DocxStyleResolver(styles_xml)

            for item in in_zf.infolist():
                raw_entry = in_zf.read(item.filename)

                # Process visible story parts: document, headers, footers, footnotes, endnotes, comments
                is_target_xml = (
                    item.filename == "word/document.xml"
                    or (item.filename.startswith("word/header") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/footer") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/footnotes") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/endnotes") and item.filename.endswith(".xml"))
                    or (item.filename.startswith("word/comments") and item.filename.endswith(".xml"))
                )

                if is_target_xml:
                    try:
                        tree = ET.fromstring(raw_entry)
                        _transform_xml_tree(
                            tree,
                            converter_fn,
                            preserve_modern_fonts=should_preserve_modern,
                            preserve_typography=preserve_typography,
                            style_resolver=style_resolver,
                        )
                        updated_entry = _serialize_xml_preserving_namespaces(tree, raw_entry)
                        out_zf.writestr(item, updated_entry)
                        continue
                    except ET.ParseError as exc:
                        if item.filename == "word/document.xml":
                            raise DoshError(
                                code=FailureCode.VALIDATION_FAILED,
                                message="Failed to parse main DOCX document body XML.",
                            ) from exc
                        if warnings is not None:
                            warnings.append(
                                WarningRecord(
                                    code="DOCX_PART_CONVERSION_FAILED",
                                    message=f"Failed to parse and convert DOCX part: {item.filename}",
                                    stage="docx_exporter",
                                )
                            )

                out_zf.writestr(item, raw_entry)

        return ArtifactPayload(
            intent=ArtifactIntent(name=filename, role=role, media_type=_DOCX_MIME_TYPE),
            content=out_buf.getvalue(),
        )
    except Exception as exc:
        if isinstance(exc, DoshError):
            raise
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="Failed to transform DOCX document structure.",
        ) from exc


def _get_run_visual_style(r: ET.Element) -> tuple:
    from sarathi.shakti.font_conversion.detector import normalize_font_family_name

    rpr = r.find(f"{{{_W_NS}}}rPr")
    if rpr is None:
        return ()
    style_tags = []
    for child in rpr:
        tag_name = child.tag.split("}")[-1]
        if tag_name in ("b", "bCs", "i", "iCs", "u", "strike", "dstrike", "color", "highlight", "sz", "szCs"):
            val = child.attrib.get(f"{{{_W_NS}}}val", "true")
            style_tags.append((tag_name, val))
        elif tag_name == "rFonts":
            fonts = tuple(sorted({
                normalize_font_family_name(v)
                for k, v in child.attrib.items()
                if k.split("}")[-1] in ("ascii", "cs", "hAnsi", "eastAsia") and v and normalize_font_family_name(v)
            }))
            if fonts:
                style_tags.append((tag_name, str(fonts)))
    return tuple(sorted(style_tags))


def _merge_adjacent_compatible_runs(container: ET.Element) -> None:
    """Merge adjacent compatible <w:r> elements without deleting semantic nodes."""
    r_tag = f"{{{_W_NS}}}r"
    t_tag = f"{{{_W_NS}}}t"

    children = list(container)
    if len(children) < 2:
        return

    i = 0
    while i < len(container) - 1:
        c1 = container[i]
        c2 = container[i + 1]
        if c1.tag == r_tag and c2.tag == r_tag:
            # Check if c2 contains any non-deletable child
            has_non_deletable = any(
                child.tag.split("}")[-1] in _NON_DELETABLE_RUN_CHILDREN
                for child in c2
            )
            style1 = _get_run_visual_style(c1)
            style2 = _get_run_visual_style(c2)
            if style1 == style2:
                t1 = c1.find(t_tag)
                t2 = c2.find(t_tag)
                if t1 is not None and t2 is not None and t2.text:
                    t1.text = (t1.text or "") + t2.text
                    if not has_non_deletable:
                        container.remove(c2)
                        continue
                    else:
                        t2.text = ""
        i += 1


def _transform_xml_tree(
    tree: ET.Element,
    converter_fn: Callable[[str], str],
    preserve_modern_fonts: bool = False,
    preserve_typography: bool = False,
    style_resolver: DocxStyleResolver | None = None,
) -> None:
    """Transform paragraphs and runs within an ElementTree OpenXML element."""
    from sarathi.shakti.font_conversion.detector import load_font_profiles, resolve_profile_from_font_name

    p_tag = f"{{{_W_NS}}}p"
    r_tag = f"{{{_W_NS}}}r"
    t_tag = f"{{{_W_NS}}}t"
    sym_tag = f"{{{_W_NS}}}sym"
    rpr_tag = f"{{{_W_NS}}}rPr"
    rfonts_tag = f"{{{_W_NS}}}rFonts"
    sz_tag = f"{{{_W_NS}}}sz"
    szcs_tag = f"{{{_W_NS}}}szCs"

    profiles = load_font_profiles()

    import inspect
    converter_takes_font = False
    try:
        sig = inspect.signature(converter_fn)
        converter_takes_font = len(sig.parameters) >= 2 or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
    except Exception:
        converter_takes_font = False

    # Process all containers that can hold runs (paragraphs, table cells, hyperlinks, sdt)
    for p in tree.iter(p_tag):
        # Merge runs at paragraph level and within sub-containers like w:hyperlink
        _merge_adjacent_compatible_runs(p)
        for sub_container in p.findall(f"{{{_W_NS}}}hyperlink"):
            _merge_adjacent_compatible_runs(sub_container)

        # Iterate all runs in paragraph (including nested)
        for parent in [p] + p.findall(f"{{{_W_NS}}}hyperlink"):
            children = list(parent)
            for child in children:
                if child.tag != r_tag:
                    continue

                # 1. Check and convert <w:sym> elements
                for sym in list(child.findall(sym_tag)):
                    sym_font = sym.attrib.get(f"{{{_W_NS}}}font")
                    sym_char = sym.attrib.get(f"{{{_W_NS}}}char")
                    if sym_font and sym_char:
                        prof_id, _ = resolve_profile_from_font_name(sym_font, profiles)
                        if prof_id and prof_id in profiles:
                            prof = profiles[prof_id]
                            hex_code = sym_char.upper()
                            if hex_code in prof.symbols:
                                mapped_char = prof.symbols[hex_code]
                                s_idx = list(child).index(sym)
                                child.remove(sym)
                                new_t = ET.Element(t_tag)
                                new_t.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                                new_t.text = mapped_char
                                child.insert(s_idx, new_t)

                # 2. Check text inside run
                t_elems = child.findall(t_tag)
                if not t_elems:
                    continue

                full_run_text = "".join(t.text for t in t_elems if t.text)
                if not full_run_text:
                    continue

                # Resolve effective font name using StyleResolver
                effective_font: str | None = None
                if style_resolver is not None:
                    effective_font = style_resolver.resolve_run_font(child, p, text=full_run_text)
                if not effective_font:
                    rpr = child.find(rpr_tag)
                    if rpr is not None:
                        rf = rpr.find(rfonts_tag)
                        if rf is not None:
                            from sarathi.shakti.font_conversion.detector import resolve_effective_font

                            effective_font = resolve_effective_font(
                                ascii_font=rf.attrib.get(f"{{{_W_NS}}}ascii"),
                                hansi_font=rf.attrib.get(f"{{{_W_NS}}}hAnsi"),
                                cs_font=rf.attrib.get(f"{{{_W_NS}}}cs"),
                                run_text=full_run_text,
                                profiles=profiles,
                            )

                # Detect if run font is modern or legacy
                resolved_prof, fam = resolve_profile_from_font_name(effective_font, profiles)
                is_modern_run = (fam == "modern") and preserve_modern_fonts

                if is_modern_run:
                    converted_text = full_run_text
                else:
                    if converter_takes_font and effective_font:
                        converted_text = converter_fn(full_run_text, font_name=effective_font)
                    else:
                        converted_text = converter_fn(full_run_text)

                segments = segment_text_by_script(converted_text)
                if not segments:
                    for t in t_elems:
                        t.text = ""
                    continue

                rpr = child.find(rpr_tag)
                if rpr is None:
                    rpr = ET.Element(rpr_tag)
                    child.insert(0, rpr)

                # If unconverted legacy text remains untouched (converted_text == full_run_text and not modern),
                # do not disguise it as modern Arial formatting.
                is_unconverted_legacy = (
                    converted_text == full_run_text
                    and fam != "modern"
                    and not any(_DEVANAGARI_CHAR_RE.match(c) for c in converted_text)
                )

                if len(segments) == 1:
                    chunk, is_dev = segments[0]
                    if not is_unconverted_legacy:
                        _apply_font_to_rpr(rpr, is_dev, rfonts_tag, sz_tag, szcs_tag, preserve_typography=preserve_typography)
                    t_elems[0].text = chunk
                    t_elems[0].attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                    for extra_t in t_elems[1:]:
                        child.remove(extra_t)
                else:
                    # Multi-script segmentation: preserve original run, update first chunk, clone formatting for rest
                    chunk0, is_dev0 = segments[0]
                    if not is_unconverted_legacy:
                        _apply_font_to_rpr(rpr, is_dev0, rfonts_tag, sz_tag, szcs_tag, preserve_typography=preserve_typography)
                    t_elems[0].text = chunk0
                    t_elems[0].attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                    for extra_t in t_elems[1:]:
                        child.remove(extra_t)

                    # Insert additional script runs after child in parent
                    c_idx = list(parent).index(child)
                    for offset, (chunk, is_dev) in enumerate(segments[1:], start=1):
                        new_r = ET.Element(r_tag)
                        new_rpr = ET.fromstring(ET.tostring(rpr))
                        if not is_unconverted_legacy:
                            _apply_font_to_rpr(new_rpr, is_dev, rfonts_tag, sz_tag, szcs_tag, preserve_typography=preserve_typography)
                        new_r.append(new_rpr)
                        new_t = ET.Element(t_tag)
                        new_t.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
                        new_t.text = chunk
                        new_r.append(new_t)
                        parent.insert(c_idx + offset, new_r)


def _apply_font_to_rpr(
    rpr: ET.Element,
    is_devanagari: bool,
    rfonts_tag: str,
    sz_tag: str,
    szcs_tag: str,
    preserve_typography: bool = False,
) -> None:
    """Set font on a <w:rPr> element, preserving original size when preserve_typography is True."""
    font = _HINDI_FONT if is_devanagari else _ENGLISH_FONT

    # Fonts
    rfonts = rpr.find(rfonts_tag)
    if rfonts is None:
        rfonts = ET.SubElement(rpr, rfonts_tag)
    rfonts.attrib[f"{{{_W_NS}}}ascii"] = font
    rfonts.attrib[f"{{{_W_NS}}}hAnsi"] = font
    rfonts.attrib[f"{{{_W_NS}}}cs"] = font

    # Size: only standardize if preserve_typography is False
    if not preserve_typography:
        size_str = str(_HINDI_HALF_PT if is_devanagari else _ENGLISH_HALF_PT)
        sz = rpr.find(sz_tag)
        if sz is None:
            sz = ET.SubElement(rpr, sz_tag)
        sz.attrib[f"{{{_W_NS}}}val"] = size_str

        szcs = rpr.find(szcs_tag)
        if szcs is None:
            szcs = ET.SubElement(rpr, szcs_tag)
        szcs.attrib[f"{{{_W_NS}}}val"] = size_str
