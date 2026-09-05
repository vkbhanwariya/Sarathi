"""End-to-End Operational Acceptance Test for Roopa Font Conversion."""

import xml.etree.ElementTree as ET
from pathlib import Path

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "krutidev_sample.txt"


def test_e2e_font_conversion_pipeline(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
    )

    inp = InputRef(
        input_id="inp-fc-1",
        source_path=_FIXTURE_PATH,
        display_name="krutidev_sample.txt",
        size_bytes=_FIXTURE_PATH.stat().st_size,
    )

    req = Request(
        request_id="req-fc-1",
        requirement="font_conversion",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"font": "krutidev010"},
    )

    ctx = ExecutionContext("run-fc-1", "req-fc-1", "t-fc", "s-fc")

    # Execute through canonical pipeline (read_native -> font_conversion)
    result = agni.execute(req, context=ctx)

    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
    doc: CanonicalDocument = result.data

    # Verify converted Devanagari and protected English spans
    assert "भारत सरकार" in doc.text
    assert "स्टेट बैंक" in doc.text
    assert "दिल्ली" in doc.text
    assert "Vendor Name" in doc.text
    assert "Invoice Number" in doc.text
    assert "Customer Reference" in doc.text
    assert "Payment Details" in doc.text
    assert "Branch Office" in doc.text
    assert "INV-998811" in doc.text
    assert "REF-SBI-2026" in doc.text
    assert "15/08/2026" in doc.text
    assert "1,50,000.00" in doc.text

    # Artifact confirmation
    assert len(result.artifacts) == 2
    art_names = {a.path.name for a in result.artifacts}
    assert "Converted_Document.txt" in art_names
    assert "Converted_Document.docx" in art_names
    for art in result.artifacts:
        assert art.path.exists()
        assert art.size_bytes > 0

    # Darpana telemetry confirmation
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0


def test_font_conversion_target_modes(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)

    agni = Agni(runtime_root=runtime_dir, output_root=output_dir, darpana=darpana)

    sample_txt = tmp_path / "hindi_sample.txt"
    sample_txt.write_text("भारत सरकार नई दिल्ली", encoding="utf-8")

    inp = InputRef(
        input_id="inp-kruti",
        source_path=sample_txt,
        display_name="hindi_sample.txt",
        size_bytes=sample_txt.stat().st_size,
    )

    # Test Convert to KrutiDev
    req_kruti = Request(
        request_id="req-kruti",
        requirement="font_conversion",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
        custom_options={"font_mode": "to_krutidev"},
    )
    ctx_kruti = ExecutionContext("run-k", "req-kruti", "t-k", "s-k")
    res_kruti = agni.execute(req_kruti, context=ctx_kruti)
    assert isinstance(res_kruti, Result)
    doc_k: CanonicalDocument = res_kruti.data
    assert "Hkkjr" in doc_k.text

    # Test Convert to DevLys
    req_devlys = Request(
        request_id="req-devlys",
        requirement="font_conversion",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
        custom_options={"font_mode": "to_devlys"},
    )
    ctx_devlys = ExecutionContext("run-d", "req-devlys", "t-d", "s-d")
    res_devlys = agni.execute(req_devlys, context=ctx_devlys)
    assert isinstance(res_devlys, Result)
    doc_d: CanonicalDocument = res_devlys.data
    assert "Hkkjr" in doc_d.text


def test_multi_page_text_artifact_preserves_page_identity() -> None:
    """Verify that multi-page documents emit standard deterministic page separators in TXT artifact."""
    from sarathi.sankalpa import PageData
    from sarathi.shakti.font_conversion.capability import FontConversionCapability

    cap = FontConversionCapability()
    p1 = PageData(page_number=1, text="eq>s vHkh ;kn gSA")
    p2 = PageData(page_number=2, text="la[;k 100 gSA")
    p3 = PageData(page_number=3, text="")  # Empty page

    doc = CanonicalDocument(
        document_id="multi-page-doc",
        source_input_id="inp-mp-1",
        pages=(p1, p2, p3),
        text="eq>s vHkh ;kn gSA\nla[;k 100 gSA\n",
    )

    req = Request(
        request_id="req-mp",
        requirement="font_conversion",
        inputs=(InputRef("inp-mp-1", source_path=_FIXTURE_PATH, display_name="test.txt", size_bytes=100),),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-mp", "req-mp", "t-mp", "s-mp")
    prior = Result(data=doc)

    res = cap.execute(req, context=ctx, prior_result=prior)
    txt_payload = next(p for p in res.artifact_payloads if p.intent.name == "Converted_Document.txt")
    txt_content = txt_payload.content.decode("utf-8")

    assert "--- Page 1 ---" in txt_content
    assert "मुझे अभी याद है।" in txt_content
    assert "--- Page 2 ---" in txt_content
    assert "संख्या १०० है।" in txt_content or "संख्या" in txt_content
    assert "--- Page 3 ---" in txt_content
    # Page order preserved
    pos1 = txt_content.index("--- Page 1 ---")
    pos2 = txt_content.index("--- Page 2 ---")
    pos3 = txt_content.index("--- Page 3 ---")
    assert pos1 < pos2 < pos3


def test_single_page_text_artifact_clean_output() -> None:
    """Verify that single-page documents do not include superfluous page separators in TXT artifact."""
    from sarathi.sankalpa import PageData
    from sarathi.shakti.font_conversion.capability import FontConversionCapability

    cap = FontConversionCapability()
    p1 = PageData(page_number=1, text="eq>s vHkh ;kn gSA")
    doc = CanonicalDocument(
        document_id="single-page-doc",
        source_input_id="inp-sp-1",
        pages=(p1,),
        text="eq>s vHkh ;kn gSA",
    )
    req = Request(
        request_id="req-sp",
        requirement="font_conversion",
        inputs=(InputRef("inp-sp-1", source_path=_FIXTURE_PATH, display_name="test.txt", size_bytes=100),),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-sp", "req-sp", "t-sp", "s-sp")
    prior = Result(data=doc)

    res = cap.execute(req, context=ctx, prior_result=prior)
    txt_payload = next(p for p in res.artifact_payloads if p.intent.name == "Converted_Document.txt")
    txt_content = txt_payload.content.decode("utf-8")
    assert "--- Page 1 ---" not in txt_content
    assert "मुझे अभी याद है।" in txt_content


def test_residual_legacy_warning_and_metrics() -> None:
    """Verify that runs with residual legacy font signatures record metrics and emit classified warnings."""
    from sarathi.sankalpa import PageData, TextSpan
    from sarathi.shakti.font_conversion.capability import FontConversionCapability

    cap = FontConversionCapability()
    # Explicit legacy font metadata with unmapped/foreign Kruti signatures
    span = TextSpan(
        text="ñòóôõ unmapped text",
        metadata={"font_name": "Kruti Dev 010", "paragraph_index": 0},
    )
    p = PageData(page_number=1, text="ñòóôõ unmapped text", spans=(span,))
    doc = CanonicalDocument(
        document_id="doc-residual",
        source_input_id="inp-res-1",
        pages=(p,),
        text="ñòóôõ unmapped text",
    )
    req = Request(
        request_id="req-res",
        requirement="font_conversion",
        inputs=(InputRef("inp-res-1", source_path=_FIXTURE_PATH, display_name="test.txt", size_bytes=100),),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-res", "req-res", "t-res", "s-res")
    prior = Result(data=doc)

    res = cap.execute(req, context=ctx, prior_result=prior)
    # Check provenance evidence for residual legacy tracking
    prov = next(pr for pr in res.provenance if pr.capability_id == "font_conversion")
    assert "residual_legacy_runs" in prov.evidence
    assert prov.evidence["runs_scanned"] >= 1


def test_canonical_and_docx_conversion_parity() -> None:
    """Verify that CanonicalDocument span conversion and raw DOCX run conversion produce identical decisions."""
    from sarathi.sankalpa import PageData, TextSpan
    from sarathi.shakti.docx_exporter import DocxStyleResolver
    from sarathi.shakti.font_conversion.detector import decide_run_profile

    # Given identical evidence: Kruti Dev font, legacy text with extended ANSI
    test_text = "LFkkÃ irk"
    font_name = "Kruti Dev 010"

    # 1. Canonical span decision
    span_decision = decide_run_profile(run_font=font_name, run_text=test_text, doc_profile="krutidev010")
    assert span_decision.decision == "convert"
    assert span_decision.profile == "krutidev010"

    # 2. Raw DOCX run decision via DocxStyleResolver and resolve_effective_font
    r = ET.fromstring(
        '<w:r xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:rPr><w:rFonts w:ascii="Kruti Dev 010" w:hAnsi="Kruti Dev 010" w:cs="Mangal"/></w:rPr>'
        '<w:t>LFkkÃ irk</w:t>'
        '</w:r>'
    )
    resolver = DocxStyleResolver()
    effective_font = resolver.resolve_run_font(r, text=test_text)
    assert effective_font == "Kruti Dev 010"

    docx_run_decision = decide_run_profile(run_font=effective_font, run_text=test_text, doc_profile="krutidev010")
    assert docx_run_decision.decision == span_decision.decision
    assert docx_run_decision.profile == span_decision.profile
