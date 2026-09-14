"""Tests for DOCX Run-Font Awareness in Font Conversion and Exporter."""

import io
import zipfile
from xml.etree import ElementTree as ET

from sarathi.shakti.docx_exporter import (
    _merge_adjacent_compatible_runs,
    transform_docx_artifact,
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


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
