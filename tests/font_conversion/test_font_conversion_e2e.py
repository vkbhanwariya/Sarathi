"""End-to-End Operational Acceptance Test for Roopa Font Conversion."""

from pathlib import Path
import pytest

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
    assert len(result.artifacts) == 1
    art = result.artifacts[0]
    assert art.path.name == "Converted_Document.txt"
    assert art.path.exists()
    assert art.size_bytes > 0

    # Darpana telemetry confirmation
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0
