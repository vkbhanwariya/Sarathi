"""E2E Pipeline Integration and Truthful Telemetry Tests with Smriti Caching."""

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


def test_pipeline_caches_and_records_factual_telemetry(tmp_path: Path) -> None:
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

    # 1. Cold execution (Cache Miss): must report miss without a false tier, with real measured duration
    ctx1 = ExecutionContext("run-1", "req-smriti-1", "t-1", "s-1")
    res1 = agni.execute(req, context=ctx1)
    assert isinstance(res1, Result)
    assert isinstance(res1.data, CanonicalDocument)
    assert res1.data.text == "Hello from Smriti verified cache pipeline!"

    recs1 = [r for r in darpana.maruti_records() if r.run_id == "run-1" and r.phase_name == "cache.lookup"]
    assert len(recs1) >= 1
    miss_rec = recs1[0]
    assert miss_rec.attributes["outcome"] == "miss"
    assert miss_rec.attributes["capability_id"] == "read_native"
    assert "cache_tier" not in miss_rec.attributes  # Must not falsely claim tier on miss
    assert isinstance(miss_rec.duration_ns, int)
    assert miss_rec.duration_ns >= 0

    # 2. Warm execution (L1 Hit): must report hit and cache_tier = l1
    ctx2 = ExecutionContext("run-2", "req-smriti-1", "t-2", "s-2")
    res2 = agni.execute(req, context=ctx2)
    assert isinstance(res2, Result)
    assert isinstance(res2.data, CanonicalDocument)
    assert res2.data.text == "Hello from Smriti verified cache pipeline!"

    recs2 = [r for r in darpana.maruti_records() if r.run_id == "run-2" and r.phase_name == "cache.lookup"]
    assert len(recs2) >= 1
    l1_hit_rec = recs2[0]
    assert l1_hit_rec.attributes["outcome"] == "hit"
    assert l1_hit_rec.attributes["cache_tier"] == "l1"
    assert l1_hit_rec.attributes["capability_id"] == "read_native"
    assert isinstance(l1_hit_rec.duration_ns, int)
    assert l1_hit_rec.duration_ns >= 0

    # 3. Warm execution after clearing L1 (L2 Hit): must report hit and cache_tier = l2
    smriti._l1.invalidate()
    assert len(smriti._l1) == 0

    ctx3 = ExecutionContext("run-3", "req-smriti-1", "t-3", "s-3")
    res3 = agni.execute(req, context=ctx3)
    assert isinstance(res3, Result)
    assert isinstance(res3.data, CanonicalDocument)
    assert res3.data.text == "Hello from Smriti verified cache pipeline!"

    recs3 = [r for r in darpana.maruti_records() if r.run_id == "run-3" and r.phase_name == "cache.lookup"]
    assert len(recs3) >= 1
    l2_hit_rec = recs3[0]
    assert l2_hit_rec.attributes["outcome"] == "hit"
    assert l2_hit_rec.attributes["cache_tier"] == "l2"
    assert l2_hit_rec.attributes["capability_id"] == "read_native"
    assert isinstance(l2_hit_rec.duration_ns, int)
    assert l2_hit_rec.duration_ns >= 0
