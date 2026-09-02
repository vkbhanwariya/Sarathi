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


@pytest.fixture
def legacy_text_file(tmp_path: Path) -> Path:
    p = tmp_path / "legacy_hindi.txt"
    p.write_text("LVsV cSad vksj Hkkjr ljdkj\nRef: SBI-2026\nAmount: Rs 50000\n", encoding="utf-8")
    return p


def test_e2e_font_conversion_pipeline(tmp_path: Path, legacy_text_file: Path) -> None:
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
        source_path=legacy_text_file,
        display_name="legacy_hindi.txt",
        size_bytes=legacy_text_file.stat().st_size,
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

    assert "भारत" in doc.text
    assert "SBI-2026" in doc.text
    assert "50000" in doc.text

    # Artifact confirmation
    assert len(result.artifacts) == 1
    art = result.artifacts[0]
    assert art.path.name == "Converted_Document.txt"
    assert art.path.exists()
    assert art.size_bytes > 0

    # Darpana telemetry confirmation
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0
