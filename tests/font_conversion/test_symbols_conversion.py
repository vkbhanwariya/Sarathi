"""Tests for OpenXML <w:sym> Symbol Conversion."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

from sarathi.shakti.docx_exporter import _W_NS, transform_docx_artifact


def _create_symbols_docx() -> bytes:
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="{_W_NS}">
      <w:body>
        <w:p>
          <!-- Run 1: Legacy KrutiDev <w:sym> with char F0B5 (micro µ) -->
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="Kruti Dev 010"/>
            </w:rPr>
            <w:sym w:font="Kruti Dev 010" w:char="F0B5"/>
          </w:r>
          <!-- Run 2: Legacy DevLys <w:sym> with char F0B1 (plus-minus ±) -->
          <w:r>
            <w:rPr>
              <w:rFonts w:ascii="DevLys 010"/>
            </w:rPr>
            <w:sym w:font="DevLys 010" w:char="F0B1"/>
          </w:r>
          <!-- Run 3: Modern Wingdings <w:sym> (should remain untouched) -->
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
