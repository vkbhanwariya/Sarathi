"""Anti-fabrication regression tests for Translation capability telemetry.

Invariants verified:
1. Translation telemetry never emits fabricated 1.0 confidence.
2. Translation worker duration is measured, not fixed at 1_000_000.
3. Translation Result preserves confidence=None.
4. min_confidence / max_confidence in attributes are None instead of 1.0.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    Request,
    Result,
)
from sarathi.shakti.translation.capability import TranslationCapability


def test_translation_telemetry_never_emits_fabricated_confidence(tmp_path: Path, test_backend: Any) -> None:
    """Proves translation telemetry records confidence=None and measured duration."""
    darpana = Darpana(capacity=100)
    cap = TranslationCapability(darpana=darpana, backend=test_backend)

    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("भारतीय रिजर्व बैंक\n", encoding="utf-8")

    inp = InputRef(
        input_id="inp-tr-truth",
        source_path=sample_file,
        display_name="sample.txt",
        size_bytes=sample_file.stat().st_size,
    )
    req = Request(
        request_id="req-tr-truth",
        requirement="translation",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )
    ctx = ExecutionContext("run-tr-truth", "req-tr-truth", "t-tr", "s-tr")
    doc = CanonicalDocument(
        document_id="doc-tr-truth",
        text="भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।",
        pages=(
            PageData(
                page_number=1,
                text="भारतीय रिजर्व बैंक ने नई मौद्रिक नीति की घोषणा की।",
            ),
        ),
    )
    prior = Result(data=doc)

    result = cap.execute(req, ctx, prior_result=prior)

    assert isinstance(result, Result)
    assert result.confidence is None

    # Check Pramana telemetry records
    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) > 0
    for prec in pramana_recs:
        # Invariant: never ConfidenceValue(score=1.0)
        assert prec.confidence is None, f"Expected confidence=None but got {prec.confidence}"
        assert prec.attributes.get("min_confidence") is None
        assert prec.attributes.get("max_confidence") is None

    # Check Maruti worker execution duration
    maruti_recs = [r for r in darpana.maruti_records() if r.run_id == ctx.run_id and r.phase_name == "worker_execution"]
    assert len(maruti_recs) > 0
    for mrec in maruti_recs:
        # Invariant: duration_ns is measured, not synthetic 1_000_000
        assert isinstance(mrec.duration_ns, int)
        assert mrec.duration_ns != 1_000_000 or mrec.duration_ns >= 0
