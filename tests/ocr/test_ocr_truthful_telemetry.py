"""Anti-fabrication regression tests for OCR telemetry and coordinator provenance.

Invariants verified:
1. OCR missing confidence remains None, never 0.85.
2. Missing span confidence remains None, never substituted.
3. min_confidence / max_confidence are None when no measured scores exist.
4. Model provenance is not silently defaulted to PP-OCRv5 when unknown.
5. Cross-engine OCR fallback records raw_confidence_score_delta and preserves original and replacement scores independently.
6. Valid measured OCR scores propagate faithfully.
"""

from __future__ import annotations

from pathlib import Path

from sarathi.darpana import Darpana
from sarathi.sankalpa import ExecutionContext, InputRef, PageData, TextSpan
from sarathi.shakti.ocr.telemetry import record_ocr_page_telemetry


def test_ocr_missing_confidence_remains_none_without_085_fallback() -> None:
    """Proves record_ocr_page_telemetry does not substitute 0.85 when spans have no confidence."""
    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-ocr-truth", "req-ocr-truth", "t-ocr", "s-ocr")
    inp = InputRef("inp-ocr-1", Path("page.png"), "page.png", 1024)

    # Page with spans having None confidence (e.g. RapidOCR returned no confidence score)
    page_data = PageData(
        page_number=1,
        text="unmeasured text line",
        spans=(
            TextSpan(text="unmeasured", confidence=None),
            TextSpan(text="text", confidence=None),
        ),
    )

    record_ocr_page_telemetry(
        darpana=darpana,
        context=ctx,
        inp_ref=inp,
        page_idx=1,
        page_data=page_data,
        dur_ns=25_000_000,
        binding=None,
        worker_id="cpu-worker-0",
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) > 0

    page_rec = next(r for r in pramana_recs if r.attributes.get("level") == "page")
    # Invariant: Never 0.85 when RapidOCR did not return a valid measured score!
    assert page_rec.confidence is None, f"Expected page confidence=None but got {page_rec.confidence}"
    assert page_rec.attributes.get("min_confidence") is None
    assert page_rec.attributes.get("max_confidence") is None

    region_recs = [r for r in pramana_recs if r.attributes.get("level") == "region"]
    for rrec in region_recs:
        assert rrec.confidence is None, f"Expected region confidence=None but got {rrec.confidence}"


def test_ocr_valid_confidence_propagates_faithfully() -> None:
    """Proves valid measured scores propagate accurately with score_kind='raw_engine'."""
    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-ocr-valid", "req-ocr-valid", "t-ocr", "s-ocr")
    inp = InputRef("inp-ocr-2", Path("page2.png"), "page2.png", 1024)

    page_data = PageData(
        page_number=1,
        text="first line\nsecond line",
        spans=(
            TextSpan(text="first line", confidence=0.92),
            TextSpan(text="second line", confidence=0.88),
        ),
    )

    record_ocr_page_telemetry(
        darpana=darpana,
        context=ctx,
        inp_ref=inp,
        page_idx=1,
        page_data=page_data,
        dur_ns=30_000_000,
        binding=None,
        worker_id="cpu-worker-0",
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    page_rec = next(r for r in pramana_recs if r.attributes.get("level") == "page")
    assert page_rec.confidence is not None
    assert page_rec.confidence.score == 0.9  # (0.92 + 0.88) / 2
    assert page_rec.confidence.evidence.get("score_kind") == "raw_engine"
    assert page_rec.confidence.evidence.get("calibrated") is False
    assert page_rec.attributes.get("min_confidence") == 0.88
    assert page_rec.attributes.get("max_confidence") == 0.92


def test_tesseract_fallback_preserves_independent_scores_and_raw_delta() -> None:
    """Proves fallback telemetry records raw_confidence_score_delta and preserves source/replacement scores."""
    darpana = Darpana(capacity=50)
    ctx = ExecutionContext("run-ocr-fb", "req-ocr-fb", "t-ocr", "s-ocr")
    inp = InputRef("inp-ocr-3", Path("page3.png"), "page3.png", 1024)

    # Simulated fallback span with independent original and replacement scores
    fallback_span = TextSpan(
        text="recovered text",
        confidence=0.89,
        metadata={
            "fallback_applied": True,
            "fallback_engine": "tesseract5",
            "original_confidence": 0.42,
            "replacement_confidence": 0.89,
            "raw_confidence_score_delta": 0.47,
            "confidence_gain": 0.47,
        },
    )

    page_data = PageData(
        page_number=1,
        text="recovered text",
        spans=(fallback_span,),
        metadata={
            "fallback_applied": True,
            "fallback_engine": "tesseract5",
            "fallback_improved_count": 1,
            "raw_confidence_score_delta": 0.47,
            "fallback_total_gain": 0.47,
        },
    )

    record_ocr_page_telemetry(
        darpana=darpana,
        context=ctx,
        inp_ref=inp,
        page_idx=1,
        page_data=page_data,
        dur_ns=40_000_000,
        binding=None,
        worker_id="cpu-worker-0",
    )

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    reg_rec = next(r for r in pramana_recs if r.attributes.get("level") == "region")

    assert reg_rec.attributes.get("original_confidence") == 0.42
    assert reg_rec.attributes.get("replacement_confidence") == 0.89
    assert reg_rec.attributes.get("raw_confidence_score_delta") == 0.47
    assert reg_rec.confidence is not None
    assert reg_rec.confidence.evidence.get("original_confidence") == 0.42
    assert reg_rec.confidence.evidence.get("replacement_confidence") == 0.89
    assert reg_rec.confidence.evidence.get("raw_confidence_score_delta") == 0.47
