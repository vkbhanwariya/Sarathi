"""End-to-End Operational Acceptance Test for Translation Capability."""

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
def hindi_sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "hindi_sample.txt"
    content = (
        "भारत सरकार का आदेश दिनांक 15/08/2026 को जारी किया गया।\n"
        "खाता संख्या SBI-998811 में ₹ 50,000.00 जमा किए गए।\n"
        "उच्च न्यायालय दिल्ली ने याचिका REF-HC-2026 को स्वीकार किया।\n"
    )
    p.write_text(content, encoding="utf-8")
    return p


def test_e2e_translation_pipeline(tmp_path: Path, hindi_sample_file: Path) -> None:
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
    )

    inp = InputRef(
        input_id="inp-tr-1",
        source_path=hindi_sample_file,
        display_name="hindi_sample.txt",
        size_bytes=hindi_sample_file.stat().st_size,
    )

    req = Request(
        request_id="req-tr-1",
        requirement="translation",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )

    ctx = ExecutionContext("run-tr-1", "req-tr-1", "t-tr", "s-tr")

    # Execute through canonical pipeline (read_native -> translation)
    result = agni.execute(req, context=ctx)

    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
    doc: CanonicalDocument = result.data

    # Verify translated text contents and factual preservation
    assert "Government of India" in doc.text
    assert "Order" in doc.text
    assert "15/08/2026" in doc.text
    assert "Account Number" in doc.text
    assert "SBI-998811" in doc.text
    assert "50,000.00" in doc.text
    assert "High Court" in doc.text
    assert "Delhi" in doc.text
    assert "REF-HC-2026" in doc.text

    # Artifact confirmation
    assert len(result.artifacts) == 1
    art = result.artifacts[0]
    assert art.path.name == "Translated_Document.txt"
    assert art.path.exists()
    assert art.size_bytes > 0

    # Darpana telemetry confirmation
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0
    pramana_recs = tuple(r for r in darpana.pramana_records() if r.run_id == ctx.run_id)
    assert len(pramana_recs) > 0
