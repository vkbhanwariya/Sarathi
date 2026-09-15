import io
import zipfile
from xml.etree import ElementTree as ET

from sarathi.shakti.docx_exporter import (
    _HINDI_FONT,
    _W_NS,
    DocxStyleResolver,
    _merge_adjacent_compatible_runs,
    transform_docx_artifact,
)
from sarathi.shakti.font_conversion.converter import FontConverter


def _create_test_docx_with_runs(runs: list[tuple[str, str | None]]) -> bytes:
    """Create a minimal in-memory DOCX with specified runs (text, font_name)."""
    document_xml = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<w:document xmlns:w="{_W_NS}">',
        "<w:body>",
        "<w:p>",
    ]
    for text, font in runs:
        document_xml.append("<w:r>")
        if font:
            document_xml.append(
                f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/></w:rPr>'
            )
        document_xml.append(f"<w:t>{text}</w:t>")
        document_xml.append("</w:r>")
    document_xml.append("</w:p>")
    document_xml.append("</w:body>")
    document_xml.append("</w:document>")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "".join(document_xml).encode("utf-8"))
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return buf.getvalue()


def test_docx_preserves_modern_devanagari_and_latin_runs() -> None:
    """Ensure modern Devanagari (Mangal) and Latin (Calibri) runs are preserved while legacy runs convert."""
    runs = [
        ("Vendor Name: ", "Calibri"),
        ("Hkkjr", "Kruti Dev 010"),
        (" नई दिल्ली ", "Mangal"),
        ("ljdkj", "Kruti Dev 010"),
    ]
    docx_bytes = _create_test_docx_with_runs(runs)

    def _sample_converter(text: str, font_name: str | None = None) -> str:
        if font_name and "kruti" in font_name.lower():
            if "Hkkjr" in text:
                return text.replace("Hkkjr", "भारत")
            if "ljdkj" in text:
                return text.replace("ljdkj", "सरकार")
        return text

    transformed_payload = transform_docx_artifact(docx_bytes, _sample_converter, filename="test.docx")
    transformed = transformed_payload.content

    # Read transformed XML
    with zipfile.ZipFile(io.BytesIO(transformed), "r") as z:
        tree = ET.fromstring(z.read("word/document.xml"))

    full_text = "".join(t.text for t in tree.iter(f"{{{_W_NS}}}t") if t.text)

    assert "Vendor Name:" in full_text
    assert "भारत" in full_text
    assert "नई दिल्ली" in full_text
    assert "सरकार" in full_text


def test_merge_krutidev_aliases() -> None:
    """Kruti Dev 010 + KrutiDev010 -> MERGE into single run."""
    p_xml = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr><w:rFonts w:ascii="Kruti Dev 010"/><w:b/><w:sz w:val="24"/></w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr><w:rFonts w:ascii="KrutiDev010"/><w:b/><w:sz w:val="24"/></w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(p_xml)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 1
    assert runs[0].find(f"{{{_W_NS}}}t").text == "Hkkjr"


def test_merge_case_and_spacing_aliases() -> None:
    """KRUTI DEV 010 + KrutiDev010 -> MERGE."""
    p_xml = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr><w:rFonts w:ascii="KRUTI DEV 010"/><w:sz w:val="20"/></w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr><w:rFonts w:ascii="KrutiDev010"/><w:sz w:val="20"/></w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(p_xml)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 1
    assert runs[0].find(f"{{{_W_NS}}}t").text == "Hkkjr"


def test_no_merge_krutidev_and_devlys() -> None:
    """KrutiDev + DevLys -> DO NOT MERGE (distinct families)."""
    p_xml = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr><w:rFonts w:ascii="KrutiDev010"/><w:b/><w:sz w:val="24"/></w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr><w:rFonts w:ascii="DevLys010"/><w:b/><w:sz w:val="24"/></w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(p_xml)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 2


def test_no_merge_krutidev_and_arial() -> None:
    """KrutiDev + Arial -> DO NOT MERGE."""
    p_xml = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr><w:rFonts w:ascii="KrutiDev010"/><w:sz w:val="24"/></w:rPr>
            <w:t>Hkkjr</w:t>
        </w:r>
        <w:r>
            <w:rPr><w:rFonts w:ascii="Arial"/><w:sz w:val="24"/></w:rPr>
            <w:t>India</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(p_xml)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 2


def test_no_merge_differing_bold() -> None:
    """Same normalized font family + different bold -> DO NOT MERGE."""
    p_xml = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr><w:rFonts w:ascii="Kruti Dev 010"/><w:b/><w:sz w:val="24"/></w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr><w:rFonts w:ascii="KrutiDev010"/><w:sz w:val="24"/></w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(p_xml)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 2


def test_no_merge_differing_size() -> None:
    """Same normalized font family + different size -> DO NOT MERGE."""
    p_xml = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr><w:rFonts w:ascii="Kruti Dev 010"/><w:sz w:val="24"/></w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr><w:rFonts w:ascii="KrutiDev010"/><w:sz w:val="28"/></w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p = ET.fromstring(p_xml)
    _merge_adjacent_compatible_runs(p)
    runs = p.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 2


def _create_mixed_docx() -> bytes:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{_W_NS}">
      <w:body>
        <w:p>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
              <w:b/>
              <w:sz w:val="32"/>
              <w:color w:val="FF0000"/>
            </w:rPr>
            <w:t>Notice: </w:t>
          </w:r>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010"/>
              <w:i/>
              <w:sz w:val="36"/>
              <w:color w:val="0000FF"/>
            </w:rPr>
            <w:t>Hkkjr ljdkj</w:t>
          </w:r>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Mangal" w:hAnsi="Mangal" w:cs="Mangal"/>
              <w:sz w:val="24"/>
            </w:rPr>
            <w:t>नई दिल्ली</w:t>
          </w:r>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>
              <w:sz w:val="20"/>
            </w:rPr>
            <w:t>REF-2026</w:t>
          </w:r>
        </w:p>
      </w:body>
    </w:document>
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        zf.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
    return buf.getvalue()


def test_mixed_font_docx_conversion_and_typography_preservation() -> None:
    """Verify mixed English, KrutiDev, and Unicode Devanagari in same paragraph retain styling."""
    raw_docx = _create_mixed_docx()
    converter = FontConverter()

    def _conv(text: str, font_name: str | None = None) -> str:
        if font_name and "kruti" in font_name.lower():
            return converter.convert(text, profile_id="krutidev010")
        return text

    payload = transform_docx_artifact(
        input_bytes=raw_docx,
        converter_fn=_conv,
        filename="mixed_test.docx",
        preserve_typography=True,
    )

    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    p = root.find(f".//{{{_W_NS}}}p")
    assert p is not None
    runs = p.findall(f"{{{_W_NS}}}r")

    # Run 1: English Calibri 32 half-pt, bold, color FF0000
    r1 = runs[0]
    t1 = r1.find(f"{{{_W_NS}}}t")
    assert t1 is not None and t1.text == "Notice: "
    rpr1 = r1.find(f"{{{_W_NS}}}rPr")
    assert rpr1.find(f"{{{_W_NS}}}b") is not None
    sz1 = rpr1.find(f"{{{_W_NS}}}sz")
    assert sz1 is not None and sz1.attrib.get(f"{{{_W_NS}}}val") == "32"
    color1 = rpr1.find(f"{{{_W_NS}}}color")
    assert color1 is not None and color1.attrib.get(f"{{{_W_NS}}}val") == "FF0000"

    # Run 2: KrutiDev converted to Unicode 'भारत सरकार' with font updated to Nirmala UI, italic, color 0000FF
    r2 = runs[1]
    t2 = r2.find(f"{{{_W_NS}}}t")
    assert t2 is not None and "भारत सरकार" in t2.text
    rpr2 = r2.find(f"{{{_W_NS}}}rPr")
    assert rpr2.find(f"{{{_W_NS}}}i") is not None
    sz2 = rpr2.find(f"{{{_W_NS}}}sz")
    assert sz2 is not None and sz2.attrib.get(f"{{{_W_NS}}}val") == "27"
    color2 = rpr2.find(f"{{{_W_NS}}}color")
    assert color2 is not None and color2.attrib.get(f"{{{_W_NS}}}val") == "0000FF"
    rf2 = rpr2.find(f"{{{_W_NS}}}rFonts")
    assert rf2.attrib.get(f"{{{_W_NS}}}ascii") == _HINDI_FONT

    # Run 3: Unicode Devanagari Mangal remains untouched
    r3 = runs[2]
    t3 = r3.find(f"{{{_W_NS}}}t")
    assert t3 is not None and "नई दिल्ली" in t3.text

    # Run 4: English reference ID preserved
    r4 = runs[3]
    t4 = r4.find(f"{{{_W_NS}}}t")
    assert t4 is not None and t4.text == "REF-2026"


def _create_symbols_docx() -> bytes:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{_W_NS}">
      <w:body>
        <w:p>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Kruti Dev 010"/>
            </w:rPr>
            <w:sym w:font="Kruti Dev 010" w:char="F0B5"/>
          </w:r>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="DevLys 010"/>
            </w:rPr>
            <w:sym w:font="DevLys 010" w:char="F0B1"/>
          </w:r>
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Wingdings"/>
            </w:rPr>
            <w:sym w:font="Wingdings" w:char="F04A"/>
          </w:r>
        </w:p>
      </w:body>
    </w:document>
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", doc_xml)
        zf.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        zf.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
    return buf.getvalue()


def test_symbols_conversion_in_docx() -> None:
    """Verify legacy <w:sym> elements are replaced by <w:t> with mapped characters, while modern symbols remain."""
    raw_docx = _create_symbols_docx()

    payload = transform_docx_artifact(
        input_bytes=raw_docx,
        converter_fn=lambda t, **kw: t,
        filename="sym_test.docx",
        preserve_typography=True,
    )

    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    runs = root.findall(f".//{{{_W_NS}}}r")
    assert len(runs) == 3

    # Run 1: KrutiDev F0B5 -> converted to <w:t>µ</w:t>
    r1 = runs[0]
    assert r1.find(f"{{{_W_NS}}}sym") is None
    t1 = r1.find(f"{{{_W_NS}}}t")
    assert t1 is not None and t1.text == "µ"

    # Run 2: DevLys F0B1 -> converted to <w:t>±</w:t>
    r2 = runs[1]
    assert r2.find(f"{{{_W_NS}}}sym") is None
    t2 = r2.find(f"{{{_W_NS}}}t")
    assert t2 is not None and t2.text == "±"

    # Run 3: Wingdings F04A -> untouched <w:sym>
    r3 = runs[2]
    sym3 = r3.find(f"{{{_W_NS}}}sym")
    assert sym3 is not None
    assert sym3.attrib.get(f"{{{_W_NS}}}font") == "Wingdings"
    assert sym3.attrib.get(f"{{{_W_NS}}}char") == "F04A"


def _make_styles_xml() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:docDefaults>
        <w:rPrDefault>
          <w:rPr>
            <w:rFonts w:ascii="DefaultAsciiFont" w:hAnsi="DefaultHAnsiFont" w:cs="DefaultCsFont"/>
          </w:rPr>
        </w:rPrDefault>
      </w:docDefaults>
      <w:style w:type="paragraph" w:styleId="BaseNormal">
        <w:rPr>
          <w:rFonts w:ascii="BaseFont" w:cs="BaseCsFont"/>
        </w:rPr>
      </w:style>
      <w:style w:type="paragraph" w:styleId="DerivedStyle">
        <w:basedOn w:val="BaseNormal"/>
      </w:style>
      <w:style w:type="paragraph" w:styleId="ParaLegacy">
        <w:rPr>
          <w:rFonts w:ascii="DevLys 010" w:hAnsi="DevLys 010" w:cs="DevLys 010"/>
        </w:rPr>
      </w:style>
      <w:style w:type="character" w:styleId="CharLegacy">
        <w:rPr>
          <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Kruti Dev 010"/>
        </w:rPr>
      </w:style>
    </w:styles>
    """


def test_direct_rpr_font_overrides_everything() -> None:
    """Verify direct run properties (rPr) override character and paragraph styles."""
    resolver = DocxStyleResolver(_make_styles_xml())

    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "ParaLegacy"

    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr = ET.SubElement(r, f"{{{_W_NS}}}rPr")
    rf = ET.SubElement(rpr, f"{{{_W_NS}}}rFonts")
    rf.attrib[f"{{{_W_NS}}}ascii"] = "Chanakya"

    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "Chanakya"


def test_character_style_overrides_paragraph_style() -> None:
    """Verify character style (rStyle) takes precedence over paragraph style (pStyle)."""
    resolver = DocxStyleResolver(_make_styles_xml())

    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "ParaLegacy"

    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr = ET.SubElement(r, f"{{{_W_NS}}}rPr")
    rstyle = ET.SubElement(rpr, f"{{{_W_NS}}}rStyle")
    rstyle.attrib[f"{{{_W_NS}}}val"] = "CharLegacy"

    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "Kruti Dev 010"


def test_paragraph_style_inheritance_when_no_char_style() -> None:
    """Verify paragraph style provides font when no direct rPr or rStyle exists."""
    resolver = DocxStyleResolver(_make_styles_xml())

    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "ParaLegacy"

    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    ET.SubElement(r, f"{{{_W_NS}}}rPr")

    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "DevLys 010"


def test_based_on_style_chain_traversal() -> None:
    """Verify styles without explicit fonts inherit from their basedOn parent style."""
    resolver = DocxStyleResolver(_make_styles_xml())

    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "DerivedStyle"

    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "BaseFont"


def test_doc_defaults_fallback() -> None:
    """Verify docDefaults rPrDefault is used when run and paragraph have no style."""
    resolver = DocxStyleResolver(_make_styles_xml())

    p = ET.Element(f"{{{_W_NS}}}p")
    r = ET.SubElement(p, f"{{{_W_NS}}}r")

    font_ascii = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font_ascii == "DefaultAsciiFont"

    font_cs = resolver.resolve_run_font(r, p, is_ascii_text=False)
    assert font_cs == "DefaultCsFont"


def test_ascii_vs_complex_script_channel_selection() -> None:
    """Verify ASCII text prefers w:ascii/w:hAnsi while Devanagari text prefers w:cs."""
    resolver = DocxStyleResolver()

    r = ET.Element(f"{{{_W_NS}}}r")
    rpr = ET.SubElement(r, f"{{{_W_NS}}}rPr")
    rf = ET.SubElement(rpr, f"{{{_W_NS}}}rFonts")
    rf.attrib[f"{{{_W_NS}}}ascii"] = "Arial"
    rf.attrib[f"{{{_W_NS}}}cs"] = "Mangal"

    assert resolver.resolve_run_font(r, is_ascii_text=True) == "Arial"
    assert resolver.resolve_run_font(r, is_ascii_text=False) == "Mangal"


def test_corrupt_or_empty_styles_xml_safe_degradation() -> None:
    """Verify corrupt styles.xml degrades gracefully to None without raising exceptions."""
    resolver_empty = DocxStyleResolver(b"")
    resolver_corrupt = DocxStyleResolver(b"NOT_XML")

    r = ET.Element(f"{{{_W_NS}}}r")
    assert resolver_empty.resolve_run_font(r) is None
    assert resolver_corrupt.resolve_run_font(r) is None
