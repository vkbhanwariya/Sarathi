"""End-to-End Operational Acceptance Test for Roopa Font Conversion."""

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
