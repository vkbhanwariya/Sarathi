"""E2E Pipeline Integration Tests with Smriti Caching."""

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
from sarathi.smriti import SmritiCache


def test_pipeline_caches_and_reuses_results(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)
    smriti = SmritiCache(cache_dir=runtime_dir / "Cache")

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
        smriti=smriti,
    )

    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Hello from Smriti verified cache pipeline!", encoding="utf-8")

    inp = InputRef(
        input_id="inp-smriti-1",
        source_path=sample_file,
        display_name="sample.txt",
        size_bytes=sample_file.stat().st_size,
    )

    req = Request(
        request_id="req-smriti-1",
        requirement="read_native",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
    )

    ctx1 = ExecutionContext("run-1", "req-smriti-1", "t-1", "s-1")

    # Run 1: Cold execution (populates Smriti cache)
    res1 = agni.execute(req, context=ctx1)
    assert isinstance(res1, Result)
    assert isinstance(res1.data, CanonicalDocument)
    assert res1.data.text == "Hello from Smriti verified cache pipeline!"

    # Run 2: Warm execution (hits Smriti cache)
    ctx2 = ExecutionContext("run-2", "req-smriti-1", "t-2", "s-2")
    res2 = agni.execute(req, context=ctx2)
    assert isinstance(res2, Result)
    assert isinstance(res2.data, CanonicalDocument)
    assert res2.data.text == "Hello from Smriti verified cache pipeline!"
