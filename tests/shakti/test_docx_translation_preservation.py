"""Focused tests for DOCX translation in-place preservation of tables, styles, and media."""

import io
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    Request,
)
from sarathi.shakti.docx_exporter import (
    _W_NS,
    transform_docx_translation_artifact,
)
from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.models import TranslationResult


def _build_minimal_test_docx(document_xml: str, extra_parts: dict[str, bytes] | None = None) -> bytes:
    """Helper to create a valid minimal DOCX zip package for testing."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
            '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
            '  <Default Extension="xml" ContentType="application/xml"/>\n'
            '  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\n'
            '</Types>',
        )
        zf.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            '  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\n'
            '</Relationships>',
        )
        zf.writestr("word/document.xml", document_xml)
        if extra_parts:
            for part_path, part_content in extra_parts.items():
                zf.writestr(part_path, part_content)
    return buf.getvalue()


def test_docx_translation_preserves_table_structure_and_merges() -> None:
    """Verify in-place translation preserves tblPr, tblGrid, gridSpan, vMerge, and shading."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p><w:r><w:t>Introduction paragraph</w:t></w:r></w:p>\n'
        '    <w:tbl>\n'
        '      <w:tblPr>\n'
        '        <w:tblW w:w="5000" w:type="dxa"/>\n'
        '        <w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/></w:tblBorders>\n'
        '      </w:tblPr>\n'
        '      <w:tblGrid>\n'
        '        <w:gridCol w:w="2500"/>\n'
        '        <w:gridCol w:w="2500"/>\n'
        '      </w:tblGrid>\n'
        '      <w:tr>\n'
        '        <w:tc>\n'
        '          <w:tcPr>\n'
        '            <w:gridSpan w:val="2"/>\n'
        '            <w:shd w:val="clear" w:color="auto" w:fill="D3D3D3"/>\n'
        '          </w:tcPr>\n'
        '          <w:p><w:r><w:t>Merged Table Header</w:t></w:r></w:p>\n'
        '        </w:tc>\n'
        '      </w:tr>\n'
        '      <w:tr>\n'
        '        <w:tc>\n'
        '          <w:tcPr><w:vMerge w:val="restart"/></w:tcPr>\n'
        '          <w:p><w:r><w:t>Vertical Cell 1</w:t></w:r></w:p>\n'
        '        </w:tc>\n'
        '        <w:tc>\n'
        '          <w:tcPr><w:vMerge/></w:tcPr>\n'
        '          <w:p><w:r><w:t>Regular Cell 2</w:t></w:r></w:p>\n'
        '        </w:tc>\n'
        '      </w:tr>\n'
        '    </w:tbl>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    raw_bytes = _build_minimal_test_docx(doc_xml)

    trans_dict = {
        "Introduction paragraph": "परिचय अनुच्छेद",
        "Merged Table Header": "विलय किया गया तालिका शीर्षक",
        "Vertical Cell 1": "ऊर्ध्वाधर कक्ष 1",
        "Regular Cell 2": "सामान्य कक्ष 2",
    }

    result = transform_docx_translation_artifact(
        raw_bytes,
        translate_fn=lambda batch: [trans_dict.get(s, s) for s in batch],
        filename="preserved_table.docx",
    )

    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    # Check table properties preserved
    tbl = root.find(f".//{{{_W_NS}}}tbl")
    assert tbl is not None, "Table must remain present"
    tbl_pr = tbl.find(f"{{{_W_NS}}}tblPr")
    assert tbl_pr is not None
    assert tbl_pr.find(f"{{{_W_NS}}}tblW") is not None
    assert tbl_pr.find(f"{{{_W_NS}}}tblBorders") is not None

    # Check grid
    tbl_grid = tbl.find(f"{{{_W_NS}}}tblGrid")
    assert tbl_grid is not None
    assert len(tbl_grid.findall(f"{{{_W_NS}}}gridCol")) == 2

    # Check merged cell and shading
    tc_prs = tbl.findall(f".//{{{_W_NS}}}tcPr")
    grid_spans = [pr.find(f"{{{_W_NS}}}gridSpan") for pr in tc_prs]
    assert any(gs is not None and gs.get(f"{{{_W_NS}}}val") == "2" for gs in grid_spans)
    shds = [pr.find(f"{{{_W_NS}}}shd") for pr in tc_prs]
    assert any(shd is not None and shd.get(f"{{{_W_NS}}}fill") == "D3D3D3" for shd in shds)

    # Check vMerge
    v_merges = [pr.find(f"{{{_W_NS}}}vMerge") for pr in tc_prs]
    assert any(vm is not None and vm.get(f"{{{_W_NS}}}val") == "restart" for vm in v_merges)

    # Check translated text content inside cells
    texts = [t.text for t in root.findall(f".//{{{_W_NS}}}t")]
    assert "परिचय अनुच्छेद" in texts
    assert "विलय किया गया तालिका शीर्षक" in texts
    assert "ऊर्ध्वाधर कक्ष 1" in texts
    assert "सामान्य कक्ष 2" in texts


def test_docx_translation_inline_formatting_reordering() -> None:
    """Verify inline formatting tags allow reordered translated text to preserve run styles."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r><w:t>Notice: </w:t></w:r>\n'
        '      <w:r><w:rPr><w:b/><w:i/></w:rPr><w:t>Payment is due</w:t></w:r>\n'
        '      <w:r><w:t> immediately.</w:t></w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    raw_bytes = _build_minimal_test_docx(doc_xml)

    def _mock_translate(batch: list[str]) -> list[str]:
        out = []
        for s in batch:
            # Source should have <fmt id="0">Payment is due</fmt>
            if '<fmt id="0">' in s:
                # Reorder the formatted span in Hindi
                out.append('<fmt id="0">भुगतान देय है</fmt> सूचना: तत्काल।')
            else:
                out.append(s)
        return out

    result = transform_docx_translation_artifact(
        raw_bytes,
        translate_fn=_mock_translate,
        filename="formatted.docx",
    )

    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    runs = root.findall(f".//{{{_W_NS}}}r")

    # Find the run containing "भुगतान देय है"
    fmt_runs = [r for r in runs if r.find(f"{{{_W_NS}}}t") is not None and "भुगतान देय है" in (r.find(f"{{{_W_NS}}}t").text or "")]
    assert len(fmt_runs) >= 1
    bold_run = fmt_runs[0]
    rpr = bold_run.find(f"{{{_W_NS}}}rPr")
    assert rpr is not None, "Formatted run must have rPr"
    assert rpr.find(f"{{{_W_NS}}}b") is not None, "Bold must be preserved"
    assert rpr.find(f"{{{_W_NS}}}i") is not None, "Italic must be preserved"

    # Verify Nirmala UI font was attached for Devanagari
    r_fonts = rpr.find(f"{{{_W_NS}}}rFonts")
    assert r_fonts is not None
    assert r_fonts.get(f"{{{_W_NS}}}ascii") == "Nirmala UI"


def test_docx_translation_preserves_media_and_non_story_parts() -> None:
    """Verify non-story parts such as word/media/image1.png and settings.xml remain bit-identical."""
    dummy_media = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    dummy_settings = b'<?xml version="1.0" encoding="UTF-8"?><w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'

    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p><w:r><w:t>Simple text</w:t></w:r></w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    raw_bytes = _build_minimal_test_docx(
        doc_xml,
        extra_parts={
            "word/media/image1.png": dummy_media,
            "word/settings.xml": dummy_settings,
        },
    )

    result = transform_docx_translation_artifact(
        raw_bytes,
        translate_fn=lambda batch: ["सरल पाठ" for _ in batch],
        filename="media_preserved.docx",
    )

    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        assert "word/media/image1.png" in zf.namelist()
        assert zf.read("word/media/image1.png") == dummy_media, "Media must be byte-for-byte identical"
        assert zf.read("word/settings.xml") == dummy_settings, "Settings must be byte-for-byte identical"


def test_docx_translation_preserves_list_numbering() -> None:
    """Verify list numbering w:numPr is preserved in paragraphs."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:pPr>\n'
        '        <w:numPr>\n'
        '          <w:ilvl w:val="0"/>\n'
        '          <w:numId w:val="5"/>\n'
        '        </w:numPr>\n'
        '      </w:pPr>\n'
        '      <w:r><w:t>First numbered item</w:t></w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    raw_bytes = _build_minimal_test_docx(doc_xml)

    result = transform_docx_translation_artifact(
        raw_bytes,
        translate_fn=lambda batch: ["पहला क्रमांकित मद" for _ in batch],
        filename="list_item.docx",
    )

    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    p = root.find(f".//{{{_W_NS}}}p")
    assert p is not None
    num_pr = p.find(f".//{{{_W_NS}}}numPr")
    assert num_pr is not None, "List numPr must be preserved"
    num_id = num_pr.find(f"{{{_W_NS}}}numId")
    assert num_id is not None and num_id.get(f"{{{_W_NS}}}val") == "5"


def test_translation_capability_dispatches_in_place_for_docx(tmp_path: Path) -> None:
    """Integration test verifying TranslationCapability uses in-place transformation when input is DOCX."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:tbl>\n'
        '      <w:tr>\n'
        '        <w:tc><w:tcPr><w:gridSpan w:val="3"/></w:tcPr><w:p><w:r><w:t>Government Notice</w:t></w:r></w:p></w:tc>\n'
        '      </w:tr>\n'
        '    </w:tbl>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    docx_file = tmp_path / "sample.docx"
    docx_file.write_bytes(_build_minimal_test_docx(doc_xml))

    # Mock translation engine
    mock_engine = MagicMock()
    mock_engine.translate.side_effect = lambda text, **kwargs: TranslationResult(
        translated_text=f"अनुवादित: {text}",
        source_language=MagicMock(value="en"),
        target_language=MagicMock(value="hi"),
        protected_spans_count=0,
    )

    cap = TranslationCapability(backend=mock_engine)

    input_ref = InputRef(
        input_id="inp-1",
        source_path=docx_file,
        display_name="sample.docx",
        size_bytes=docx_file.stat().st_size,
    )
    req = Request(
        request_id="req-1",
        requirement="translation",
        inputs=(input_ref,),
        metadata={"direction": "en-hi"},
    )
    ctx = ExecutionContext("run-1", "req-1", "t-1", "s-1")
    prior_doc = CanonicalDocument(
        document_id="doc-1",
        source_input_id="inp-1",
        text="Government Notice",
    )
    from sarathi.sankalpa import Result as SankalpaResult
    prior_result = SankalpaResult(data=prior_doc)

    result = cap.execute(req, ctx, prior_result=prior_result)
    assert result.data is not None
    docx_payload = next(p for p in result.artifact_payloads if p.intent.role == "translated_document")
    assert docx_payload.intent.name.endswith(".docx")

    # Verify that the generated DOCX preserved the table and gridSpan
    with zipfile.ZipFile(io.BytesIO(docx_payload.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    tbl = root.find(f".//{{{_W_NS}}}tbl")
    assert tbl is not None, "In-place table must be retained in translated DOCX payload"
    grid_span = tbl.find(f".//{{{_W_NS}}}gridSpan")
    assert grid_span is not None and grid_span.get(f"{{{_W_NS}}}val") == "3"


def test_docx_translation_uniform_runs_emit_clean_text() -> None:
    """Verify paragraphs with uniform formatting emit clean text without <fmt> tags and retain style."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r><w:rPr><w:b/></w:rPr><w:t>Case Name *</w:t></w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    raw_bytes = _build_minimal_test_docx(doc_xml)

    captured_inputs: list[str] = []

    def _spy_translate(batch: list[str]) -> list[str]:
        captured_inputs.extend(batch)
        return ["केस का नाम *" for _ in batch]

    result = transform_docx_translation_artifact(
        raw_bytes,
        translate_fn=_spy_translate,
        filename="uniform_styled.docx",
    )

    # 1. Verify clean text was sent without pseudo-XML markup
    assert len(captured_inputs) == 1
    assert captured_inputs[0] == "Case Name *"
    assert "<fmt" not in captured_inputs[0]

    # 2. Verify reconstructed document preserves the bold styling
    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    t_elem = root.find(f".//{{{_W_NS}}}t")
    assert t_elem is not None and t_elem.text == "केस का नाम *"
    r_elem = root.find(f".//{{{_W_NS}}}r")
    assert r_elem is not None
    rpr = r_elem.find(f"{{{_W_NS}}}rPr")
    assert rpr is not None and rpr.find(f"{{{_W_NS}}}b") is not None


def test_docx_translation_sanitizes_hallucinated_tags_and_repetition_loops() -> None:
    """Verify that hallucinated <fmt idmir...> and runaway <br/> loops from NMT do not leak."""
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
        '  <w:body>\n'
        '    <w:p>\n'
        '      <w:r><w:t>Notice: </w:t></w:r>\n'
        '      <w:r><w:rPr><w:b/></w:rPr><w:t>Confidential</w:t></w:r>\n'
        '    </w:p>\n'
        '  </w:body>\n'
        '</w:document>'
    )
    raw_bytes = _build_minimal_test_docx(doc_xml)

    # Simulate NMT returning hallucinated <fmt idmir'0'> tag and repeated <br/> loop
    def _hallucinating_translate(batch: list[str]) -> list[str]:
        return [
            "< fmt idmir′0′ गोपनीय / fmt′ < br / > < br / > < br / > < br / >"
        ]

    result = transform_docx_translation_artifact(
        raw_bytes,
        translate_fn=_hallucinating_translate,
        filename="sanitized.docx",
    )

    with zipfile.ZipFile(io.BytesIO(result.content), "r") as zf:
        out_xml = zf.read("word/document.xml").decode("utf-8")

    root = ET.fromstring(out_xml)
    runs = root.findall(f".//{{{_W_NS}}}r")
    full_text = " ".join(r.find(f"{{{_W_NS}}}t").text or "" for r in runs if r.find(f"{{{_W_NS}}}t") is not None)

    # Corrupted tags must be stripped and not leaked into final DOCX
    assert "idmir" not in full_text
    assert "< fmt" not in full_text
    assert "/ fmt" not in full_text
    assert "< br" not in full_text
    assert "गोपनीय" in full_text
