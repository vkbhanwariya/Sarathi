"""Integration Tests for In-Place Multi-Part DOCX XML Transcoding (Phase 5)."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

from sarathi.shakti.docx_exporter.constants import _W_NS
from sarathi.shakti.docx_exporter.transformer import transform_docx_artifact
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import load_font_profiles


def _build_multipart_test_docx() -> bytes:
    """Construct an in-memory multi-part DOCX containing body, header, footer, footnote, and table."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # [Content_Types].xml
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
    <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
    <Override PartName="/word/footnotes.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>
</Types>""",
        )

        # word/header1.xml with KrutiDev text: "dk;kZy; ftyk dysDVj" ("कार्यालय जिला कलक्टर")
        zf.writestr(
            "word/header1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:p>
        <w:r>
            <w:rPr>
                <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Kruti Dev 010"/>
            </w:rPr>
            <w:t>dk;kZy; ftyk dysDVj</w:t>
        </w:r>
    </w:p>
</w:hdr>""",
        )

        # word/footer1.xml with KrutiDev text: "i`" ("पृ")
        zf.writestr(
            "word/footer1.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:p>
        <w:r>
            <w:rPr>
                <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Kruti Dev 010"/>
            </w:rPr>
            <w:t>i`</w:t>
        </w:r>
    </w:p>
</w:ftr>""",
        )

        # word/footnotes.xml with KrutiDev text: "Hkkjr" ("भारत")
        zf.writestr(
            "word/footnotes.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:footnote w:id="1">
        <w:p>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Kruti Dev 010"/>
                </w:rPr>
                <w:t>Hkkjr</w:t>
            </w:r>
        </w:p>
    </w:footnote>
</w:footnotes>""",
        )

        # word/document.xml with body text and table
        zf.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <w:body>
        <w:p>
            <w:r>
                <w:rPr>
                    <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Kruti Dev 010"/>
                    <w:sz w:val="28"/>
                </w:rPr>
                <w:t>Hkkjr ljdkj</w:t>
            </w:r>
        </w:p>
        <w:tbl>
            <w:tr>
                <w:tc>
                    <w:p>
                        <w:r>
                            <w:rPr>
                                <w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Kruti Dev 010"/>
                            </w:rPr>
                            <w:t>x`g ea=ky;</w:t>
                        </w:r>
                    </w:p>
                </w:tc>
            </w:tr>
        </w:tbl>
    </w:body>
</w:document>""",
        )

    return buf.getvalue()


def test_multipart_docx_transcoding_all_parts() -> None:
    """Verify in-place transcoding converts document body, headers, footers, footnotes, and tables."""
    input_bytes = _build_multipart_test_docx()
    profiles = load_font_profiles()
    converter = FontConverter(profiles=profiles)

    def convert_fn(text: str, font_name: str | None = None) -> str:
        return converter.convert(text, profile_id="krutidev010")

    result = transform_docx_artifact(
        input_bytes=input_bytes,
        converter_fn=convert_fn,
        filename="test_converted.docx",
        profiles=profiles,
        normalize_font_sizes=True,
    )

    assert result.intent.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    out_buf = io.BytesIO(result.content)

    with zipfile.ZipFile(out_buf, "r") as zf:
        # 1. Verify Header Part Transcoded
        hdr_xml = zf.read("word/header1.xml")
        hdr_tree = ET.fromstring(hdr_xml)
        hdr_text = "".join(hdr_tree.itertext()).strip()
        assert "कार्यालय जिला कलेक्टर" in hdr_text
        hdr_rfonts = hdr_tree.find(f".//{{{_W_NS}}}rFonts")
        assert hdr_rfonts is not None
        assert hdr_rfonts.attrib.get(f"{{{_W_NS}}}cs") in ("Nirmala UI", "Mangal")

        # 2. Verify Footer Part Transcoded
        ftr_xml = zf.read("word/footer1.xml")
        ftr_tree = ET.fromstring(ftr_xml)
        ftr_text = "".join(ftr_tree.itertext()).strip()
        assert "पृ" in ftr_text
        ftr_rfonts = ftr_tree.find(f".//{{{_W_NS}}}rFonts")
        assert ftr_rfonts is not None
        assert ftr_rfonts.attrib.get(f"{{{_W_NS}}}cs") in ("Nirmala UI", "Mangal")

        # 3. Verify Footnotes Part Transcoded
        fn_xml = zf.read("word/footnotes.xml")
        fn_tree = ET.fromstring(fn_xml)
        fn_text = "".join(fn_tree.itertext()).strip()
        assert "भारत" in fn_text

        # 4. Verify Document Body & Table Transcoded
        doc_xml = zf.read("word/document.xml")
        doc_tree = ET.fromstring(doc_xml)
        doc_text = "".join(doc_tree.itertext())
        assert "भारत सरकार" in doc_text
        assert "गृह मंत्रालय" in doc_text

        # 5. Verify Font Size Normalization applied
        body_sz = doc_tree.find(f".//{{{_W_NS}}}p//{{{_W_NS}}}sz")
        assert body_sz is not None
        # 28 half-pt (14pt) scaled down by font normalizer (~0.85x)
        assert int(body_sz.attrib.get(f"{{{_W_NS}}}val", 0)) < 28
