"""Tests for OpenXML StyleResolver and Effective Font Resolution Hierarchy."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from sarathi.shakti.docx_exporter import _W_NS, DocxStyleResolver


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

    # Paragraph with ParaLegacy style
    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "ParaLegacy"

    # Run with direct rPr font
    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr = ET.SubElement(r, f"{{{_W_NS}}}rPr")
    rf = ET.SubElement(rpr, f"{{{_W_NS}}}rFonts")
    rf.attrib[f"{{{_W_NS}}}ascii"] = "Chanakya"

    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "Chanakya"


def test_character_style_overrides_paragraph_style() -> None:
    """Verify character style (rStyle) takes precedence over paragraph style (pStyle)."""
    resolver = DocxStyleResolver(_make_styles_xml())

    # Paragraph with ParaLegacy style (DevLys 010)
    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "ParaLegacy"

    # Run with CharLegacy style (Kruti Dev 010) and no direct rFonts
    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    rpr = ET.SubElement(r, f"{{{_W_NS}}}rPr")
    rstyle = ET.SubElement(rpr, f"{{{_W_NS}}}rStyle")
    rstyle.attrib[f"{{{_W_NS}}}val"] = "CharLegacy"

    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "Kruti Dev 010"


def test_paragraph_style_inheritance_when_no_char_style() -> None:
    """Verify paragraph style provides font when no direct rPr or rStyle exists."""
    resolver = DocxStyleResolver(_make_styles_xml())

    # Paragraph with ParaLegacy style (DevLys 010)
    p = ET.Element(f"{{{_W_NS}}}p")
    ppr = ET.SubElement(p, f"{{{_W_NS}}}pPr")
    pstyle = ET.SubElement(ppr, f"{{{_W_NS}}}pStyle")
    pstyle.attrib[f"{{{_W_NS}}}val"] = "ParaLegacy"

    # Run with empty rPr
    r = ET.SubElement(p, f"{{{_W_NS}}}r")
    ET.SubElement(r, f"{{{_W_NS}}}rPr")

    font = resolver.resolve_run_font(r, p, is_ascii_text=True)
    assert font == "DevLys 010"


def test_based_on_style_chain_traversal() -> None:
    """Verify styles without explicit fonts inherit from their basedOn parent style."""
    resolver = DocxStyleResolver(_make_styles_xml())

    # Paragraph with DerivedStyle (basedOn BaseNormal)
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
