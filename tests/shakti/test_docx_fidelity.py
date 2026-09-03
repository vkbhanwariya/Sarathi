"""Tests for DOCX export fidelity, table deduplication, and multi-run transformation."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

from sarathi.sankalpa import CanonicalDocument, PageData, TableData
from sarathi.shakti.docx_exporter import (
    _W_NS,
    build_docx_payload,
    transform_docx_artifact,
)


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
        tables=(tbl,),  # Also aggregated at document level
    )

    payload = build_docx_payload(doc, filename="output.docx")
    assert payload.intent.name == "output.docx"

    with zipfile.ZipFile(io.BytesIO(payload.content)) as zf:
        doc_xml = zf.read("word/document.xml")
        root = ET.fromstring(doc_xml)
        tbl_elems = root.findall(f".//{{{_W_NS}}}tbl")
        # Must be exactly 1 table, not 2
        assert len(tbl_elems) == 1


def test_transform_docx_merges_adjacent_runs_across_word_boundaries() -> None:
    """Verify transform_docx_artifact merges adjacent runs with identical formatting."""
    # Build a minimal DOCX with a word split across two runs with identical properties
    p_xml = (
        f'<w:p xmlns:w="{_W_NS}">'
        f'<w:r><w:rPr><w:b/></w:rPr><w:t>Kruti</w:t></w:r>'
        f'<w:r><w:rPr><w:b/></w:rPr><w:t>Dev</w:t></w:r>'
        f'</w:p>'
    )
    doc_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>{p_xml}</w:body></w:document>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))

    # Converter expects whole word "KrutiDev"
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
        # Verify word was transformed as a unit
        assert "Devanagari" in full_text
