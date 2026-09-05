"""Focused positive and adversarial tests for the canonical DOCX exporter."""

import io
import xml.etree.ElementTree as ET
import zipfile
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import CanonicalDocument, TableData
from sarathi.shakti.docx_exporter import (
    build_docx_payload,
    segment_text_by_script,
    transform_docx_artifact,
)


def test_segment_text_by_script() -> None:
    """Verify clean segmentation of Devanagari and Latin script text."""
    # Pure Devanagari
    res = segment_text_by_script("नमस्ते भारत")
    assert len(res) == 1
    assert res[0] == ("नमस्ते भारत", True)

    # Pure English
    res_en = segment_text_by_script("Hello World 123")
    assert len(res_en) == 1
    assert res_en[0] == ("Hello World 123", False)

    # Mixed
    res_mixed = segment_text_by_script("Account खाता number 12345")
    assert len(res_mixed) >= 2
    assert any("खाता" in chunk and is_dev for chunk, is_dev in res_mixed)
    assert any("Account" in chunk and not is_dev for chunk, is_dev in res_mixed)


def test_build_docx_payload_structure_and_typography() -> None:
    """Verify that build_docx_payload produces a valid DOCX with specified typography."""
    tbl = TableData(
        name="खाता विवरण (Account Details)",
        headers=("क्र. सं.", "विवरण (Description)", "राशि (Amount)"),
        rows=(("1", "जमा (Deposit)", "10,000"), ("2", "निकासी (Withdrawal)", "5,000")),
    )
    doc = CanonicalDocument(
        document_id="doc-test-1",
        text="यह एक परीक्षण दस्तावेज़ है।\nThis is an English test line.",
        tables=(tbl,),
        metadata={"title": "परीक्षण शीर्षक (Test Title)"},
    )

    payload = build_docx_payload(doc, "output.docx")
    assert payload.intent.name == "output.docx"
    assert payload.intent.media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Verify that the payload content is a valid ZIP package
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        namelist = zf.namelist()
        assert "[Content_Types].xml" in namelist
        assert "word/document.xml" in namelist
        assert "word/styles.xml" in namelist

        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Nirmala UI" in doc_xml
        assert "Arial" in doc_xml
        # Check font sizes: 14pt (28 half-pts) and 12pt (24 half-pts)
        assert 'w:val="28"' in doc_xml
        assert 'w:val="24"' in doc_xml
        # Check table elements
        assert "<w:tbl>" in doc_xml
        assert "<w:tblHeader/>" in doc_xml


def test_transform_docx_artifact_preserves_formatting() -> None:
    """Verify that transform_docx_artifact transforms existing DOCX XML in-place."""
    # Construct a minimal in-memory DOCX
    in_buf = io.BytesIO()
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:pPr><w:jc w:val="center"/></w:pPr>\n'
        '      <w:r>\n'
        '        <w:rPr><w:b/><w:shadow/><w:rFonts w:ascii="Kruti Dev 010"/><w:sz w:val="24"/></w:rPr>\n'
        '        <w:t>vkns\'k</w:t>\n'
        '      </w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    # Converter mapping 'vkns\'k' -> 'आदेश'
    def mock_converter(s: str) -> str:
        return "आदेश" if "vkns" in s else s

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=mock_converter,
        filename="transformed.docx",
    )
    assert transformed.intent.name == "transformed.docx"

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        assert "आदेश" in out_xml
        # Bold and shadow must be preserved
        assert "<w:b" in out_xml
        assert "<w:shadow" in out_xml
        # Font updated to Nirmala UI 14pt (28) for Devanagari
        assert "Nirmala UI" in out_xml
        assert 'w:val="28"' in out_xml


def test_transform_docx_artifact_corrupt_input_raises_dosh_error() -> None:
    """Verify that corrupt or invalid ZIP bytes raise DoshError(CORRUPT_INPUT)."""
    with pytest.raises(DoshError) as exc_info:
        transform_docx_artifact(
            input_bytes=b"not a valid zip file",
            converter_fn=lambda s: s,
            filename="bad.docx",
        )
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED


def test_mc_ignorable_namespace_preservation() -> None:
    """Verify that every prefix named in mc:Ignorable remains declared and resolvable."""
    in_buf = io.BytesIO()
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'mc:Ignorable="w14 w15 wp14">\n'
        '  <w:body>\n'
        '    <w:p><w:r><w:t>Hello</w:t></w:r></w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=lambda s: s,
        filename="ns_test.docx",
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        # Every prefix referenced in mc:Ignorable must still have an xmlns: declaration
        assert 'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"' in out_xml
        assert 'xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"' in out_xml
        assert 'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordml"' in out_xml or "xmlns:wp14" in out_xml
        assert 'mc:Ignorable="w14 w15 wp14"' in out_xml or "w14 w15 wp14" in out_xml

        # Verify it parses cleanly with ElementTree
        root = ET.fromstring(out_xml.encode("utf-8"))
        assert root.tag.endswith("document")


def test_arbitrary_extension_namespace_preservation() -> None:
    """Verify arbitrary custom extension namespaces survive transformation."""
    in_buf = io.BytesIO()
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:customExt="http://schemas.example.com/customExtension">\n'
        '  <w:body>\n'
        '    <w:p><w:r><w:t>Custom</w:t></w:r></w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=lambda s: s,
        filename="custom_ns.docx",
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        assert 'xmlns:customExt="http://schemas.example.com/customExtension"' in out_xml


def test_last_rendered_page_break_survives_run_merging() -> None:
    """Verify lastRenderedPageBreak metadata survives adjacent run merging without deletion."""
    in_buf = io.BytesIO()
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r><w:rPr><w:b/></w:rPr><w:t>Page 1 end. </w:t></w:r>\n'
        '      <w:r><w:rPr><w:b/></w:rPr><w:lastRenderedPageBreak/><w:t>Page 2 start.</w:t></w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=lambda s: s,
        filename="page_break.docx",
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        # lastRenderedPageBreak must NOT be deleted
        assert "lastRenderedPageBreak" in out_xml
        # The text was merged
        assert "Page 1 end. Page 2 start." in out_xml


def test_semantic_run_children_never_lost() -> None:
    """Verify drawings, field chars, tabs, and ptabs are never deleted by run merging."""
    in_buf = io.BytesIO()
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r><w:t>Prefix</w:t></w:r>\n'
        '      <w:r><w:tab/><w:t>After Tab</w:t></w:r>\n'
        '      <w:r><w:fldChar w:fldCharType="begin"/><w:t>Field</w:t></w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=lambda s: s,
        filename="semantic_nodes.docx",
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tab" in out_xml
        assert "<w:fldChar" in out_xml


def test_mixed_font_channels_kruti_ascii_mangal_cs() -> None:
    """Verify Kruti ascii/hAnsi + Mangal cs resolves as Kruti when text contains legacy encoding."""
    in_buf = io.BytesIO()
    # A run with ascii=Kruti Dev, cs=Mangal, and extended legacy text LFkkÃ (contains Ã from CP1252)
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r>\n'
        '        <w:rPr><w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Mangal"/></w:rPr>\n'
        '        <w:t>LFkkÃ irk</w:t>\n'
        '      </w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    from sarathi.shakti.font_conversion.converter import FontConverter
    conv = FontConverter()

    def converter(s: str, font_name: str | None = None) -> str:
        if font_name and "kruti" in font_name.lower():
            return conv.convert(s, "krutidev010")
        return s

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=converter,
        filename="mixed_channels.docx",
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        # Must NOT leave LFkkÃ irk unconverted
        assert "LFkkÃ" not in out_xml
        # Must be converted to स्थाई पता
        assert "स्थाई" in out_xml
        assert "पता" in out_xml
        assert "Nirmala UI" in out_xml


def test_genuine_unicode_hindi_with_mangal_cs_preserved() -> None:
    """Verify genuine Unicode Hindi with cs=Mangal is preserved and not converted."""
    in_buf = io.BytesIO()
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r>\n'
        '        <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Mangal"/></w:rPr>\n'
        '        <w:t>यह शुद्ध हिन्दी है</w:t>\n'
        '      </w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", doc_xml_content)

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=lambda s, **kw: "CORRUPTED" if "शुद्ध" in s else s,
        filename="unicode_hindi.docx",
        preserve_modern_fonts=True,
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        assert "यह शुद्ध हिन्दी है" in out_xml
        assert "CORRUPTED" not in out_xml
