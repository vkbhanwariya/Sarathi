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
