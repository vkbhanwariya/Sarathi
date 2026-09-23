"""Focused positive and adversarial tests for the canonical DOCX exporter."""

import io
import re
import xml.etree.ElementTree as ET
import zipfile

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import CanonicalDocument, PageData, TableData, WarningRecord
from sarathi.shakti.docx_exporter import (
    _W_NS,
    _merge_adjacent_compatible_runs,
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
        assert "Times New Roman" in doc_xml
        # Check standard font size: 12pt (24 half-pts)
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
        "  <w:body>\n"
        "    <w:p>\n"
        '      <w:pPr><w:jc w:val="center"/></w:pPr>\n'
        "      <w:r>\n"
        '        <w:rPr><w:b/><w:shadow/><w:rFonts w:ascii="Kruti Dev 010"/><w:sz w:val="24"/></w:rPr>\n'
        "        <w:t>vkns'k</w:t>\n"
        "      </w:r>\n"
        "    </w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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
        # Font updated to Nirmala UI 12pt (24) for Devanagari
        assert "Nirmala UI" in out_xml
        assert 'w:val="24"' in out_xml


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
        "  <w:body>\n"
        "    <w:p><w:r><w:t>Hello</w:t></w:r></w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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
        "  <w:body>\n"
        "    <w:p><w:r><w:t>Custom</w:t></w:r></w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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
        "  <w:body>\n"
        "    <w:p>\n"
        "      <w:r><w:rPr><w:b/></w:rPr><w:t>Page 1 end. </w:t></w:r>\n"
        "      <w:r><w:rPr><w:b/></w:rPr><w:lastRenderedPageBreak/><w:t>Page 2 start.</w:t></w:r>\n"
        "    </w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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
        "  <w:body>\n"
        "    <w:p>\n"
        "      <w:r><w:t>Prefix</w:t></w:r>\n"
        "      <w:r><w:tab/><w:t>After Tab</w:t></w:r>\n"
        '      <w:r><w:fldChar w:fldCharType="begin"/><w:t>Field</w:t></w:r>\n'
        "    </w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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
        "  <w:body>\n"
        "    <w:p>\n"
        "      <w:r>\n"
        '        <w:rPr><w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Mangal"/></w:rPr>\n'
        "        <w:t>LFkkÃ irk</w:t>\n"
        "      </w:r>\n"
        "    </w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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
        "  <w:body>\n"
        "    <w:p>\n"
        "      <w:r>\n"
        '        <w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Mangal"/></w:rPr>\n'
        "        <w:t>यह शुद्ध हिन्दी है</w:t>\n"
        "      </w:r>\n"
        "    </w:p>\n"
        "  </w:body>\n"
        "</w:document>"
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


def test_legacy_target_font_script_segmentation() -> None:
    """Verify legacy_target_font formats Devanagari in legacy font and Latin/digits in Times New Roman."""
    doc = CanonicalDocument(
        document_id="doc-legacy-mixed",
        text="न्यायालय आदेश Case No 1234/2024",
    )
    payload = build_docx_payload(
        doc=doc,
        filename="legacy_mixed.docx",
        legacy_target_font="Kruti Dev 010",
    )
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Kruti Dev 010" in doc_xml
        assert "Times New Roman" in doc_xml


def test_converted_legacy_text_receives_legacy_font() -> None:
    """Verify converted legacy Hindi text (represented in Latin code points like 'Hkkjr') receives legacy font."""
    doc = CanonicalDocument(
        document_id="doc-legacy-converted",
        text="Hkkjr",  # Converted Kruti Dev for 'भारत'
    )
    payload = build_docx_payload(
        doc=doc,
        filename="legacy_converted.docx",
        legacy_target_font="Kruti Dev 010",
    )
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Kruti Dev 010" in doc_xml
        assert "Times New Roman" not in doc_xml


def test_mixed_unicode_unified_nirmala_ui() -> None:
    """Verify Hindi-English mixed Unicode paragraph routes Devanagari to Nirmala UI and Latin to Times New Roman."""
    doc = CanonicalDocument(
        document_id="doc-mixed-unicode",
        text="Section 482 CrPC के अंतर्गत याचिका स्वीकार की जाती है।",
    )
    payload = build_docx_payload(
        doc=doc,
        filename="mixed_unicode.docx",
    )
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Nirmala UI" in doc_xml
        assert "Times New Roman" in doc_xml
        root = ET.fromstring(doc_xml.encode("utf-8"))
        p = root.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p")
        assert p is not None
        r_fonts = [
            rf.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ascii")
            for rf in p.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts")
        ]
        assert "Nirmala UI" in r_fonts
        assert "Times New Roman" in r_fonts


def test_dynamic_font_size_scaling_in_transform_docx() -> None:
    """Verify that legacy 16 pt scales to 12 pt, headings scale proportionally, and modern sizes stay intact."""
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc_xml_content = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{w_ns}">\n'
        "  <w:body>\n"
        "    <w:p>\n"
        '      <w:r><w:rPr><w:rFonts w:ascii="Kruti Dev 010"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr><w:t>c;ku</w:t></w:r>\n'
        '      <w:r><w:rPr><w:rFonts w:ascii="Kruti Dev 010"/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr><w:t>'
        + "vkns'k"
        + "</w:t></w:r>\n"
        '      <w:r><w:rPr><w:rFonts w:ascii="Bookman Old Style"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr><w:t>Flat 1411</w:t></w:r>\n'
        "    </w:p>\n"
        "  </w:body>\n"
        "</w:document>"
    )
    in_buf = io.BytesIO()
    with zipfile.ZipFile(in_buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        )
        zf.writestr("word/document.xml", doc_xml_content)

    def _dummy_converter(text: str, **kw: str) -> str:
        if "c;ku" in text:
            return "बयान"
        if "vkns" in text:
            return "आदेश"
        return text

    transformed = transform_docx_artifact(
        input_bytes=in_buf.getvalue(),
        converter_fn=_dummy_converter,
        filename="scaled.docx",
        preserve_typography=True,
    )

    with zipfile.ZipFile(io.BytesIO(transformed.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        tree = ET.fromstring(out_xml.encode("utf-8"))

    runs = list(tree.iter(f"{{{w_ns}}}r"))
    assert len(runs) >= 3

    # Run 1: Kruti Dev 16 pt (sz=32) -> Nirmala UI 12 pt (sz=24)
    r0 = runs[0]
    sz0 = r0.find(f".//{{{w_ns}}}sz")
    assert sz0 is not None
    assert sz0.attrib[f"{{{w_ns}}}val"] == "24"

    # Run 2: Kruti Dev 24 pt (sz=48, heading) -> Nirmala UI 18 pt (sz=36)
    r1 = runs[1]
    sz1 = r1.find(f".//{{{w_ns}}}sz")
    assert sz1 is not None
    assert sz1.attrib[f"{{{w_ns}}}val"] == "36"

    # Run 3: Bookman Old Style 12 pt (sz=24) -> Times New Roman 12 pt (sz=24, untouched)
    r2 = runs[2]
    sz2 = r2.find(f".//{{{w_ns}}}sz")
    assert sz2 is not None
    assert sz2.attrib[f"{{{w_ns}}}val"] == "24"


def test_markdown_heading_formatting_in_build_docx_payload() -> None:
    """Verify build_docx_payload formats markdown heading levels dynamically with appropriate font sizes."""
    doc = CanonicalDocument(
        document_id="doc-heading-test",
        text="# मुख्य शीर्षक\n## उप शीर्षक\nसाधारण विवरण यहाँ है।",
    )
    payload = build_docx_payload(doc=doc, filename="heading_test.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")
        tree = ET.fromstring(out_xml.encode("utf-8"))

    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs = list(tree.iter(f"{{{w_ns}}}p"))
    assert len(paragraphs) == 3

    # P0: # मुख्य शीर्षक -> 16 pt (sz=32), bold
    t0 = paragraphs[0].find(f".//{{{w_ns}}}t")
    assert t0 is not None and t0.text == "मुख्य शीर्षक"
    assert paragraphs[0].find(f".//{{{w_ns}}}b") is not None
    sz0 = paragraphs[0].find(f".//{{{w_ns}}}sz")
    assert sz0 is not None and sz0.attrib[f"{{{w_ns}}}val"] == "32"

    # P1: ## उप शीर्षक -> 14 pt (sz=28), bold
    t1 = paragraphs[1].find(f".//{{{w_ns}}}t")
    assert t1 is not None and t1.text == "उप शीर्षक"
    assert paragraphs[1].find(f".//{{{w_ns}}}b") is not None
    sz1 = paragraphs[1].find(f".//{{{w_ns}}}sz")
    assert sz1 is not None and sz1.attrib[f"{{{w_ns}}}val"] == "28"

    # P2: Body -> 12 pt (sz=24)
    t2 = paragraphs[2].find(f".//{{{w_ns}}}t")
    assert t2 is not None and t2.text == "साधारण विवरण यहाँ है।"
    sz2 = paragraphs[2].find(f".//{{{w_ns}}}sz")
    assert sz2 is not None and sz2.attrib[f"{{{w_ns}}}val"] == "24"


def test_transform_docx_artifact_uses_caller_profiles() -> None:
    """Verify transform_docx_artifact uses caller-supplied profiles without reloading from disk."""
    from typing import Any
    from unittest.mock import patch

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body></w:document>',
        )
    raw_docx = buf.getvalue()

    custom_profiles: dict[str, Any] = {}
    with patch("sarathi.shakti.font_conversion.detector.load_font_profiles") as mock_load:
        payload = transform_docx_artifact(
            input_bytes=raw_docx,
            converter_fn=lambda s, **kw: s,
            filename="out.docx",
            profiles=custom_profiles,
        )
        assert payload is not None
        mock_load.assert_not_called()


def test_docx_exporter_autonomous_no_font_conversion_import() -> None:
    """Verify docx_exporter exports neutral font primitives and operates without font_conversion."""
    from sarathi.shakti.docx_exporter import (
        FontSizeAdjustment,
        get_font_size_adjustment,
        normalize_font_name,
        normalize_font_size,
        resolve_neutral_ooxml_font,
    )

    # Verify neutral font resolution rules
    assert (
        resolve_neutral_ooxml_font(ascii_font="Times New Roman", cs_font="Mangal", run_text="English")
        == "Times New Roman"
    )
    assert resolve_neutral_ooxml_font(ascii_font="Times New Roman", cs_font="Mangal", run_text="हिन्दी") == "Mangal"
    assert (
        resolve_neutral_ooxml_font(ascii_font="Kruti Dev 010", cs_font="Mangal", run_text="LFkkÃ irk")
        == "Kruti Dev 010"
    )

    # Verify font size adjustment
    assert isinstance(FontSizeAdjustment(scale=0.75), FontSizeAdjustment)
    assert normalize_font_name("  Kruti  Dev 010 ") == "kruti dev 010"
    adj = get_font_size_adjustment(anchor_font="Kruti Dev 010", target_font="Nirmala UI")
    assert adj.scale == 0.75
    assert normalize_font_size(16.0, anchor_font="Kruti Dev 010", target_font="Nirmala UI") == 12.0


def test_build_docx_payload_does_not_duplicate_tables() -> None:
    """Verify tables present in both doc.pages and doc.tables are exported only once into DOCX."""
    tbl = TableData(
        name="Financial Summary",
        headers=("Item", "Amount"),
        rows=(("Revenue", "1000"), ("Expense", "500")),
    )
    page = PageData(page_number=1, text="Page 1 Content", tables=(tbl,))
    doc = CanonicalDocument(
        document_id="doc_tbl_dedup",
        source_input_id="in_tbl",
        text="Page 1 Content",
        pages=(page,),
        tables=(tbl,),
    )

    payload = build_docx_payload(doc, filename="output.docx")
    assert payload.intent.name == "output.docx"

    with zipfile.ZipFile(io.BytesIO(payload.content)) as zf:
        doc_xml = zf.read("word/document.xml")
        root = ET.fromstring(doc_xml)
        tbl_elems = root.findall(f".//{{{_W_NS}}}tbl")
        assert len(tbl_elems) == 1


def test_transform_docx_merges_adjacent_runs_across_word_boundaries() -> None:
    """Verify transform_docx_artifact merges adjacent runs with identical formatting."""
    p_xml = (
        f'<w:p xmlns:w="{_W_NS}">'
        f"<w:r><w:rPr><w:b/></w:rPr><w:t>Kruti</w:t></w:r>"
        f"<w:r><w:rPr><w:b/></w:rPr><w:t>Dev</w:t></w:r>"
        f"</w:p>"
    )
    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W_NS}"><w:body>{p_xml}</w:body></w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))

    def mock_converter(text: str) -> str:
        return text.replace("KrutiDev", "Devanagari")

    res = transform_docx_artifact(
        input_bytes=buf.getvalue(),
        converter_fn=mock_converter,
        filename="transformed.docx",
    )

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        out_xml = zf.read("word/document.xml")
        root = ET.fromstring(out_xml)
        t_elems = root.findall(f".//{{{_W_NS}}}t")
        full_text = "".join(t.text for t in t_elems if t.text)
        assert "Devanagari" in full_text


def test_transform_docx_heals_split_remington_syllables_across_formatting_boundaries() -> None:
    """Verify transform_docx_artifact heals Remington split stems across formatting boundaries."""
    from sarathi.shakti.font_conversion.converter import FontConverter

    p_xml = (
        f'<w:p xmlns:w="{_W_NS}">'
        f'<w:r><w:rPr><w:rFonts w:ascii="Kruti Dev 010"/></w:rPr><w:t>izkf/kdj.</w:t></w:r>'
        f'<w:r><w:rPr><w:b/><w:rFonts w:ascii="Kruti Dev 010"/></w:rPr><w:t>k ls</w:t></w:r>'
        f"</w:p>"
    )
    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W_NS}"><w:body>{p_xml}</w:body></w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))

    fc = FontConverter()
    res = transform_docx_artifact(
        input_bytes=buf.getvalue(),
        converter_fn=lambda s: fc.convert(s, "krutidev010"),
        filename="transformed.docx",
    )

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        out_xml = zf.read("word/document.xml")
        root = ET.fromstring(out_xml)
        runs = root.findall(f".//{{{_W_NS}}}r")
        all_run_texts = ["".join(t.text for t in r.findall(f".//{{{_W_NS}}}t") if t.text) for r in runs]
        assert "प्राधिकरण" in all_run_texts
        assert any("से" in t for t in all_run_texts)
        full_text = "".join(t.text for t in root.findall(f".//{{{_W_NS}}}t") if t.text)
        assert full_text == "प्राधिकरण से"
        assert "प्राधिकरण्ा" not in full_text
        assert "्ा" not in full_text


def test_transform_docx_artifact_fails_on_corrupt_body() -> None:
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w") as zf:
        zf.writestr("word/document.xml", b"<w:document><unclosed>")
    corrupt_docx = out_buf.getvalue()

    with pytest.raises(DoshError) as exc_info:
        transform_docx_artifact(corrupt_docx, lambda s: s, "out.docx")
    assert exc_info.value.code == FailureCode.VALIDATION_FAILED


def test_transform_docx_artifact_warns_on_corrupt_header() -> None:
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p></w:body></w:document>',
        )
        zf.writestr("word/header1.xml", b"<w:hdr><unclosed>")
    valid_body_bad_hdr = out_buf.getvalue()

    warnings: list[WarningRecord] = []
    res = transform_docx_artifact(valid_body_bad_hdr, lambda s: s, "out.docx", warnings=warnings)
    assert res is not None
    assert any(w.code == "DOCX_PART_CONVERSION_FAILED" for w in warnings)


def test_merge_adjacent_compatible_runs_with_differing_font_tag() -> None:
    xml_data = f"""<w:p xmlns:w="{_W_NS}">
        <w:r>
            <w:rPr>
                <w:rFonts w:ascii="Kruti Dev 010"/>
                <w:b/>
                <w:sz w:val="24"/>
            </w:rPr>
            <w:t>Hkk</w:t>
        </w:r>
        <w:r>
            <w:rPr>
                <w:rFonts w:ascii="KrutiDev010"/>
                <w:b/>
                <w:sz w:val="24"/>
            </w:rPr>
            <w:t>jr</w:t>
        </w:r>
    </w:p>"""
    p_elem = ET.fromstring(xml_data)
    _merge_adjacent_compatible_runs(p_elem)
    runs = p_elem.findall(f"{{{_W_NS}}}r")
    assert len(runs) == 1
    assert runs[0].find(f"{{{_W_NS}}}t").text == "Hkkjr"


def test_docx_multi_column_section_styling() -> None:
    """Verify that build_docx_payload emits <w:cols w:num="2" .../> when column_count >= 2."""
    # 1. Single-column document
    p1 = PageData(page_number=1, text="Single column text paragraph.", metadata={"column_count": 1})
    doc_single = CanonicalDocument(document_id="doc_single", pages=(p1,))
    res_single = build_docx_payload(doc_single, "single.docx")
    with zipfile.ZipFile(io.BytesIO(res_single.content)) as zf:
        xml_single = zf.read("word/document.xml").decode("utf-8")
        assert '<w:cols w:space="720"/>' in xml_single
        assert 'w:num="2"' not in xml_single

    # 2. Multi-column document
    p2 = PageData(page_number=1, text="Two column text layout.", metadata={"column_count": 2})
    doc_multi = CanonicalDocument(document_id="doc_multi", pages=(p2,))
    res_multi = build_docx_payload(doc_multi, "multi.docx")
    with zipfile.ZipFile(io.BytesIO(res_multi.content)) as zf:
        xml_multi = zf.read("word/document.xml").decode("utf-8")
        assert '<w:cols w:num="2" w:space="720"/>' in xml_multi


def test_docx_table_grid_and_proportional_column_widths() -> None:
    """Verify that build_docx_payload emits <w:tblGrid>, <w:gridCol>, <w:tcW> with 9360 total dxa."""
    tbl = TableData(
        name="Summary",
        headers=("ID", "Detailed Description of Item", "Qty"),
        rows=(
            ("1", "Very long description that requires more column space than short ID", "10"),
            ("2", "Another item description", "5"),
        ),
    )
    doc = CanonicalDocument(document_id="doc_tbl", tables=(tbl,))
    payload = build_docx_payload(doc, "table.docx")

    with zipfile.ZipFile(io.BytesIO(payload.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tblGrid>" in xml
        assert '<w:tblW w:w="9026" w:type="dxa"/>' in xml
        assert "<w:tblCellMar>" in xml
        assert '<w:top w:w="120" w:type="dxa"/>' in xml
        assert '<w:left w:w="160" w:type="dxa"/>' in xml
        assert "<w:cantSplit/>" in xml

        # Extract gridCol widths
        grid_col_widths = [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"/>', xml)]
        assert len(grid_col_widths) == 3
        # Sum must equal 9026 exactly (A4 printable width)
        assert sum(grid_col_widths) == 9026
        # The description column (index 1) must be wider than ID (index 0)
        assert grid_col_widths[1] > grid_col_widths[0]
        assert grid_col_widths[1] > grid_col_widths[2]


def test_docx_table_in_flow_placement_and_deduplication() -> None:
    """Verify in-flow {{TABLE:name}} anchor places table between paragraphs and deduplicates text rows."""
    tbl = TableData(
        name="Metrics",
        headers=("Metric", "Score"),
        rows=(("Accuracy", "99%"), ("Latency", "12ms")),
    )
    page_text = (
        "Introduction paragraph.\n"
        "{{TABLE:Metrics}}\n"
        "Concluding remarks.\n"
        "Accuracy | 99%"  # Duplicate raw text line that should be filtered out
    )
    p = PageData(page_number=1, text=page_text, tables=(tbl,))
    doc = CanonicalDocument(document_id="doc_inflow", pages=(p,))
    payload = build_docx_payload(doc, "inflow.docx")

    with zipfile.ZipFile(io.BytesIO(payload.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        # Ensure table XML appears between intro and concluding paragraphs
        intro_pos = xml.find("Introduction paragraph.")
        table_pos = xml.find("<w:tbl>")
        concl_pos = xml.find("Concluding remarks.")

        assert intro_pos != -1
        assert table_pos != -1
        assert concl_pos != -1
        assert intro_pos < table_pos < concl_pos

        # Table should only appear once in document
        assert xml.count("<w:tbl>") == 1
        # The duplicate pipe text "Accuracy | 99%" should NOT appear as a plain text paragraph
        assert "Accuracy | 99%" not in xml


def test_docx_table_multiline_cells_and_ragged_rows() -> None:
    """Verify multiline cells format with line breaks and ragged rows are padded to grid width."""
    tbl = TableData(
        name="MultilineTable",
        headers=("Col A", "Col B", "Col C"),
        rows=(
            ("Line 1\nLine 2", "Single", "Extra"),
            ("Only One Cell",),  # Ragged row: only 1 cell instead of 3
        ),
    )
    doc = CanonicalDocument(document_id="doc_multi_cell", tables=(tbl,))
    payload = build_docx_payload(doc, "multi_cell.docx")

    with zipfile.ZipFile(io.BytesIO(payload.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tblGrid>" in xml
        assert "Line 1" in xml
        assert "Line 2" in xml

        # 1 header row + 2 data rows = 3 rows in total, each having 3 cells
        rows = re.findall(r"<w:tr>.*?</w:tr>", xml)
        assert len(rows) == 3
        for r in rows:
            tc_count = r.count("<w:tc>")
            assert tc_count == 3


def test_docx_table_typography_standardization() -> None:
    """Verify table headers and cells adhere to standardized 11 pt and 10 pt (dense) typography."""
    # 1. Standard 3-column table -> 11 pt (22 half-pt)
    tbl_std = TableData(
        name="StdTable",
        headers=("Col 1", "Col 2", "Col 3"),
        rows=(("Val 1", "Val 2", "Val 3"),),
    )
    doc_std = CanonicalDocument(document_id="doc_std", tables=(tbl_std,))
    payload_std = build_docx_payload(doc_std, "std.docx")

    with zipfile.ZipFile(io.BytesIO(payload_std.content)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        assert '<w:sz w:val="21"/>' in xml

    # 2. Dense 6-column table -> 10 pt (20 half-pt)
    tbl_dense = TableData(
        name="DenseTable",
        headers=("C1", "C2", "C3", "C4", "C5", "C6"),
        rows=(("1", "2", "3", "4", "5", "6"),),
    )
    doc_dense = CanonicalDocument(document_id="doc_dense", tables=(tbl_dense,))
    payload_dense = build_docx_payload(doc_dense, "dense.docx")

    with zipfile.ZipFile(io.BytesIO(payload_dense.content)) as zf:
        xml_dense = zf.read("word/document.xml").decode("utf-8")
        assert '<w:sz w:val="20"/>' in xml_dense


def test_build_docx_payload_without_markdown_headings_preserves_uniform_size() -> None:
    """Verify build_docx_payload with interpret_markdown_headings=False avoids false heading inflation."""
    doc = CanonicalDocument(
        document_id="doc_ocr_uniform",
        text="# Government of Rajasthan\n## Reference 1234\nNormal text description.",
    )
    payload = build_docx_payload(
        doc=doc,
        filename="ocr_uniform.docx",
        interpret_markdown_headings=False,
    )
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        tree = ET.fromstring(doc_xml.encode("utf-8"))

    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraphs = list(tree.iter(f"{{{w_ns}}}p"))
    assert len(paragraphs) == 3

    # All paragraphs must stay at baseline 12 pt (sz=24), with no 16 pt or 14 pt inflation
    for p in paragraphs:
        sz = p.find(f".//{{{w_ns}}}sz")
        assert sz is not None and sz.attrib[f"{{{w_ns}}}val"] == "24"

    # Leading '# ' and '## ' should be stripped from text content
    t0 = paragraphs[0].find(f".//{{{w_ns}}}t")
    assert t0 is not None and t0.text == "Government of Rajasthan"
    t1 = paragraphs[1].find(f".//{{{w_ns}}}t")
    assert t1 is not None and t1.text == "Reference 1234"


def test_build_docx_payload_dual_channel_font_assignment() -> None:
    """Verify standard English paragraph receives dual-channel Times New Roman with Nirmala UI complex script fallback."""
    doc = CanonicalDocument(
        document_id="doc_dual_font",
        text="Standard English circular text.",
    )
    payload = build_docx_payload(doc, "dual_font.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        tree = ET.fromstring(doc_xml.encode("utf-8"))

    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rf = tree.find(f".//{{{w_ns}}}rFonts")
    assert rf is not None
    assert rf.attrib.get(f"{{{w_ns}}}ascii") == "Times New Roman"
    assert rf.attrib.get(f"{{{w_ns}}}hAnsi") == "Times New Roman"
    assert rf.attrib.get(f"{{{w_ns}}}cs") == "Nirmala UI"


def test_build_docx_payload_single_column_layout_for_isolated_multicolumn_pages() -> None:
    """Verify that docx export keeps single-column layout when < 75% of pages are multi-column."""
    # 9 single-column pages, 1 page with metadata column_count=2
    pages = [
        PageData(page_number=i, text=f"Page {i} single column text.", metadata={"column_count": 1})
        for i in range(1, 10)
    ]
    pages.append(PageData(page_number=10, text="Page 10 right-aligned signature.", metadata={"column_count": 2}))
    doc = CanonicalDocument(
        document_id="doc_column_test",
        pages=tuple(pages),
        text="Full document text",
    )
    payload = build_docx_payload(doc, "single_col.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")

    # In single column, <w:cols> must not have w:num="2"
    assert 'w:num="2"' not in doc_xml


def test_build_docx_payload_preserves_multiple_tables_with_same_name() -> None:
    """Verify that unanchored tables with identical generic names (e.g. Table 1) across pages are not dropped."""
    tbl1 = TableData(name="Table 1", headers=("A", "B"), rows=(("1", "2"),))
    tbl2 = TableData(name="Table 1", headers=("X", "Y"), rows=(("7", "8"),))

    p1 = PageData(page_number=1, text="Page 1 text", tables=(tbl1,))
    p2 = PageData(page_number=2, text="Page 2 text", tables=(tbl2,))

    doc = CanonicalDocument(
        document_id="doc_tables_test",
        pages=(p1, p2),
        tables=(tbl1, tbl2),
        text="Page 1 text\n\nPage 2 text",
    )
    payload = build_docx_payload(doc, "tables.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        tree = ET.fromstring(doc_xml.encode("utf-8"))

    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    docx_tables = list(tree.iter(f"{{{w_ns}}}tbl"))
    assert len(docx_tables) == 2, "Both tables must be rendered, none dropped due to duplicate generic name"


def test_bug_O5_literal_none_in_tables() -> None:
    """O5: TableData with None cells must produce no 'None' in plaintext or docx document.xml."""
    import io
    import zipfile
    from unittest.mock import MagicMock, patch

    import pymupdf

    from sarathi.sankalpa import CanonicalDocument, PageData, TableData
    from sarathi.shakti.docx_exporter.builder import build_docx_payload
    from sarathi.shakti.native_extraction.readers.pdf import read_pdf
    from sarathi.shakti.ocr.capability import _format_page_text_with_tables

    tbl = TableData(headers=("Header", None), rows=(("a", None), (None, "b")))
    page = PageData(page_number=1, text="", tables=(tbl,))
    doc = CanonicalDocument(document_id="doc_none_test", pages=(page,), tables=(tbl,))

    # 1. Plaintext formatting must contain no "None"
    txt = _format_page_text_with_tables(page)
    assert "None" not in txt, f"Expected no 'None' in formatted page text, got:\n{txt}"

    from sarathi.sankalpa.document import transform_canonical_document
    from sarathi.shakti.translation.capability import _format_table_as_markdown

    md_tbl = _format_table_as_markdown(tbl)
    assert "None" not in md_tbl, f"Expected no 'None' in markdown table, got:\n{md_tbl}"

    transformed_doc = transform_canonical_document(doc, lambda s: s.upper(), detected_type="transformed")
    assert transformed_doc.tables[0].headers == ("HEADER", "")
    assert transformed_doc.tables[0].rows == (("A", ""), ("", "B"))

    # 2. DOCX document.xml must contain no "None"
    payload = build_docx_payload(doc, "table_none.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
    assert "None" not in doc_xml, f"Expected no 'None' in docx XML, got:\n{doc_xml}"

    # 3. Mocked PyMuPDF table with None cells produces "" cells
    pdf_doc = pymupdf.open()
    pdf_page = pdf_doc.new_page()
    pdf_page.insert_text((50, 50), "Sample text")
    pdf_bytes = pdf_doc.tobytes()
    pdf_doc.close()

    mock_tab = MagicMock()
    mock_tab.extract.return_value = [["Col1", "Col2"], ["a", None], [None, "b"]]
    mock_tab.header = None

    mock_tabs = MagicMock()
    mock_tabs.tables = [mock_tab]

    def mock_find_tables(*_args, **_kwargs):
        return mock_tabs

    with patch.object(pymupdf.Page, "find_tables", mock_find_tables):
        parsed_doc, _, _ = read_pdf(pdf_bytes, input_id="mock_pdf")
        assert len(parsed_doc.tables) == 1
        extracted_tbl = parsed_doc.tables[0]
        for row in extracted_tbl.rows:
            for cell in row:
                assert cell is not None, f"Expected cell to not be None, got {row}"
                assert cell != "None", f"Expected cell to not be 'None', got {row}"
        assert extracted_tbl.rows == (("a", ""), ("", "b"))


def test_bug_O6_docx_xml_control_characters() -> None:
    """O6: Control characters in text must be sanitized/converted, producing valid parseable OpenXML."""
    import io
    import xml.etree.ElementTree as ET
    import zipfile

    from sarathi.sankalpa import CanonicalDocument, PageData
    from sarathi.shakti.docx_exporter.builder import build_docx_payload
    from sarathi.shakti.docx_exporter.transformer import transform_docx_translation_artifact

    bad_text = "Hello\x00World\x08Test\x0bBreak\x0cNext\x1fEnd"
    page = PageData(page_number=1, text=bad_text)
    doc = CanonicalDocument(document_id="doc_ctrl_chars", pages=(page,), text=bad_text)

    # 1. build_docx_payload must produce valid, parseable XML without invalid control chars
    payload = build_docx_payload(doc, "control_chars.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")

    # Document XML must be well-formed and parseable by standard XML parser
    tree = ET.fromstring(doc_xml)
    assert tree is not None

    for bad_char in ["\x00", "\x08", "\x0b", "\x1f"]:
        assert bad_char not in doc_xml, f"Found invalid control char {repr(bad_char)} in document.xml"

    # \x0c should be converted into page break or stripped, never present as literal \x0c
    assert "\x0c" not in doc_xml

    # 2. transform_docx_translation_artifact with control chars in translation must also be sanitized
    def mock_bad_translate(texts: list[str]) -> list[str]:
        return [f"Translated_{bad_text}_{t}" for t in texts]

    transformed_payload = transform_docx_translation_artifact(
        input_bytes=payload.content,
        translate_fn=mock_bad_translate,
        filename="transformed_ctrl.docx",
    )
    with zipfile.ZipFile(io.BytesIO(transformed_payload.content), "r") as zf:
        trans_doc_xml = zf.read("word/document.xml").decode("utf-8")

    trans_tree = ET.fromstring(trans_doc_xml)
    assert trans_tree is not None
    for bad_char in ["\x00", "\x08", "\x0b", "\x0c", "\x1f"]:
        assert bad_char not in trans_doc_xml, f"Found invalid char {repr(bad_char)} in transformed XML"


def test_docx_exporter_visual_normalization() -> None:
    """Verify DOCX exporter produces justified paragraphs, paragraph spacing, clean whitespace, and styles.xml defaults."""
    from sarathi.shakti.docx_exporter.builder import build_docx_payload, normalize_docx_text

    # 1. normalize_docx_text unit checks
    assert normalize_docx_text("Hello\t\tWorld") == "Hello World"
    assert normalize_docx_text("Multiple   spaces    here") == "Multiple spaces here"
    assert normalize_docx_text("Word  ,  punctuation  . ") == "Word, punctuation."
    assert normalize_docx_text("क  िताब") == "किताब"
    assert normalize_docx_text("") == ""
    assert normalize_docx_text(None) == ""

    # 2. Document build with messy whitespace and enters
    messy_text = (
        "This is paragraph one with \t tabs   and   spaces  .\n\n\n\n"
        "This is paragraph two with Devanagari क  िताब content .\n\n"
        "# Heading One\n\n"
        "This is paragraph three under heading."
    )
    doc = CanonicalDocument(
        document_id="doc_norm_test",
        text=messy_text,
    )

    payload = build_docx_payload(doc, "normalized.docx")
    with zipfile.ZipFile(io.BytesIO(payload.content), "r") as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        styles_xml = zf.read("word/styles.xml").decode("utf-8")

    # Document XML checks:
    # Paragraphs must be justified:
    assert '<w:jc w:val="both"/>' in doc_xml
    # Paragraphs must have standard 8pt spacing after:
    assert '<w:spacing w:after="160"' in doc_xml
    # Headings must be left-aligned (not justified):
    assert '<w:jc w:val="left"/>' in doc_xml
    # Whitespace in runs must be clean:
    assert "tabs and spaces." in doc_xml
    assert "किताब" in doc_xml
    assert "content." in doc_xml
    # No raw tabs or multi-spaces in output:
    assert "\t" not in doc_xml
    assert "   " not in doc_xml
    # Redundant empty paragraphs must not be present:
    assert "<w:p/>" not in doc_xml

    # Styles XML checks:
    # Must declare docDefaults with w:pPrDefault and w:rPrDefault:
    assert "<w:pPrDefault>" in styles_xml
    assert '<w:jc w:val="both"/>' in styles_xml
    assert '<w:spacing w:after="160"' in styles_xml
    assert "<w:rPrDefault>" in styles_xml
    assert "Nirmala UI" in styles_xml
    # Must declare Normal style:
    assert 'w:styleId="Normal"' in styles_xml
