"""Anti-fabrication regression tests for Font Conversion telemetry.

Invariants verified:
1. conf=None remains None in Pramana records, never defaults to 0.95.
2. Missing span confidence remains None, not synthesized from detector score.
3. Fixed duration 1_000_000 is eliminated.
4. Heuristic detector method is labelled accurately (not roopa_coverage_weighted) and tagged heuristic/uncalibrated.
"""

from __future__ import annotations

from pathlib import Path

from sarathi.darpana import Darpana
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, TextSpan
from sarathi.shakti.font_conversion.telemetry import emit_conversion_telemetry


def test_font_telemetry_preserves_none_without_095_fallback() -> None:
    """Proves emit_conversion_telemetry never falls back to 0.95 when conf is None."""
    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-font-truth", "req-font-truth", "t-fc", "s-fc")
    doc = CanonicalDocument(
        document_id="doc-font-1",
        pages=(
            PageData(
                page_number=1,
                text="sample text",
                spans=(
                    TextSpan(text="sample", confidence=None),
                    TextSpan(text="text", confidence=None),
                ),
            ),
        ),
    )
    naming_inp = InputRef("inp-1", Path("doc.txt"), "doc.txt", 100)

    emit_conversion_telemetry(
        darpana=darpana,
        context=ctx,
        doc=doc,
        naming_inp=naming_inp,
        conf=None,
        dur_ns=12_345,
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) > 0
    for prec in pramana_recs:
        # Invariant: confidence must be None, never ConfidenceValue(score=0.95)
        assert prec.confidence is None, f"Expected confidence=None but got {prec.confidence}"
        assert prec.attributes.get("min_confidence") is None
        assert prec.attributes.get("max_confidence") is None

    maruti_recs = [r for r in darpana.maruti_records() if r.run_id == ctx.run_id and r.phase_name == "worker_execution"]
    assert len(maruti_recs) == 1
    assert maruti_recs[0].duration_ns == 12_345  # Not fixed 1_000_000!


def test_font_telemetry_does_not_synthesize_span_confidence_from_page() -> None:
    """Proves span with confidence=None remains None even when page has detector score."""
    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-font-span", "req-font-span", "t-fc", "s-fc")
    doc = CanonicalDocument(
        document_id="doc-font-2",
        pages=(
            PageData(
                page_number=1,
                text="sample text",
                spans=(
                    TextSpan(text="sample", confidence=None),  # Missing span score
                    TextSpan(text="text", confidence=0.88),   # Present span score
                ),
            ),
        ),
    )
    naming_inp = InputRef("inp-2", Path("doc.txt"), "doc.txt", 100)

    emit_conversion_telemetry(
        darpana=darpana,
        context=ctx,
        doc=doc,
        naming_inp=naming_inp,
        conf=0.90,
        dur_ns=50_000,
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    region_recs = [r for r in pramana_recs if r.attributes.get("level") == "region"]
    assert len(region_recs) == 2

    # First span had confidence=None -> must remain None!
    assert region_recs[0].confidence is None

    # Second span had confidence=0.88 -> preserved and tagged heuristic
    assert region_recs[1].confidence is not None
    assert region_recs[1].confidence.score == 0.88
    assert region_recs[1].confidence.evidence.get("score_kind") == "heuristic"
    assert region_recs[1].confidence.evidence.get("calibrated") is False
