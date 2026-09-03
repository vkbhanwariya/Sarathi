"""End-to-End Operational Acceptance Test for Translation Capability."""

from pathlib import Path
from typing import Any

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
from sarathi.shakti.bank_statements import BankStatementCapability
from sarathi.shakti.darshana import DarshanaCapability
from sarathi.shakti.font_conversion import FontConversionCapability
from sarathi.shakti.native_extraction import NativeExtractionCapability
from sarathi.shakti.ocr import OCRCapability
from sarathi.shakti.translation.capability import TranslationCapability


@pytest.fixture
def hindi_sample_file(tmp_path: Path) -> Path:
    p = tmp_path / "hindi_sample.txt"
    content = "भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।\n"
    p.write_text(content, encoding="utf-8")
    return p


def test_e2e_translation_pipeline(tmp_path: Path, hindi_sample_file: Path, test_backend: Any) -> None:
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)

    # Injected test backend to verify pipeline without binary neural weights in git
    test_cap = TranslationCapability(darpana=darpana, backend=test_backend)

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
        capabilities={
            "identify": DarshanaCapability(),
            "read_native": NativeExtractionCapability(),
            "ocr": OCRCapability(),
            "bank_statements": BankStatementCapability(darpana=darpana),
            "font_conversion": FontConversionCapability(darpana=darpana),
            "translation": test_cap,
        },
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

    # Verify translated text contents
    assert "Reserve Bank of India" in doc.text
    assert "announced the new monetary policy" in doc.text

    # Artifact confirmation
    assert len(result.artifacts) == 2
    art_names = {a.path.name for a in result.artifacts}
    assert "Translated_Document.txt" in art_names
    assert "Translated_Document.docx" in art_names
    for art in result.artifacts:
        assert art.path.exists()
        assert art.size_bytes > 0

    # Darpana telemetry confirmation
    maruti_recs = tuple(r for r in darpana.maruti_records() if r.run_id == ctx.run_id)
    assert len(maruti_recs) > 0
