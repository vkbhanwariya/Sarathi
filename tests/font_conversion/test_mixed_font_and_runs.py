"""Tests for Mixed-Font Handling, Run Segmentation, and Typography Preservation."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

from sarathi.shakti.docx_exporter import (
    _HINDI_FONT,
    _W_NS,
    transform_docx_artifact,
)
from sarathi.shakti.font_conversion.converter import FontConverter


def _create_mixed_docx() -> bytes:
    """Create a minimal in-memory DOCX with mixed English, KrutiDev, and Unicode Devanagari runs."""
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{_W_NS}">
      <w:body>
        <w:p>
          <!-- Run 1: English header, 16pt, bold -->
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
              <w:b/>
              <w:sz w:val="32"/>
              <w:color w:val="FF0000"/>
            </w:rPr>
            <w:t>Notice: </w:t>
          </w:r>
          <!-- Run 2: KrutiDev legacy Hindi, 18pt, italic -->
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010"/>
              <w:i/>
              <w:sz w:val="36"/>
              <w:color w:val="0000FF"/>
            </w:rPr>
            <w:t>Hkkjr ljdkj</w:t>
          </w:r>
          <!-- Run 3: Existing modern Unicode Devanagari, 12pt -->
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Mangal" w:hAnsi="Mangal" w:cs="Mangal"/>
              <w:sz w:val="24"/>
            </w:rPr>
            <w:t>नई दिल्ली</w:t>
          </w:r>
          <!-- Run 4: English reference ID, 10pt -->
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

    # Run 1: English remains untouched with Calibri and 32 half-pt (16pt), bold, color FF0000
    r1 = runs[0]
    t1 = r1.find(f"{{{_W_NS}}}t")
    assert t1 is not None and t1.text == "Notice: "
    rpr1 = r1.find(f"{{{_W_NS}}}rPr")
    assert rpr1.find(f"{{{_W_NS}}}b") is not None
    sz1 = rpr1.find(f"{{{_W_NS}}}sz")
    assert sz1 is not None and sz1.attrib.get(f"{{{_W_NS}}}val") == "32"
    color1 = rpr1.find(f"{{{_W_NS}}}color")
    assert color1 is not None and color1.attrib.get(f"{{{_W_NS}}}val") == "FF0000"

    # Run 2: KrutiDev converted to Unicode 'भारत सरकार' with font updated to Nirmala UI, but 36 half-pt (18pt) preserved, italic, color 0000FF
    r2 = runs[1]
    t2 = r2.find(f"{{{_W_NS}}}t")
    assert t2 is not None and "भारत सरकार" in t2.text
    rpr2 = r2.find(f"{{{_W_NS}}}rPr")
    assert rpr2.find(f"{{{_W_NS}}}i") is not None
    sz2 = rpr2.find(f"{{{_W_NS}}}sz")
    assert sz2 is not None and sz2.attrib.get(f"{{{_W_NS}}}val") == "36"  # Preserved original 18pt!
    color2 = rpr2.find(f"{{{_W_NS}}}color")
    assert color2 is not None and color2.attrib.get(f"{{{_W_NS}}}val") == "0000FF"
    rf2 = rpr2.find(f"{{{_W_NS}}}rFonts")
    assert rf2.attrib.get(f"{{{_W_NS}}}ascii") == _HINDI_FONT

    # Run 3: Unicode Devanagari Mangal remains untouched with 24 half-pt (12pt)
    r3 = runs[2]
    t3 = r3.find(f"{{{_W_NS}}}t")
    assert t3 is not None and "नई दिल्ली" in t3.text

    # Run 4: English reference ID preserved
    r4 = runs[3]
    t4 = r4.find(f"{{{_W_NS}}}t")
    assert t4 is not None and t4.text == "REF-2026"
