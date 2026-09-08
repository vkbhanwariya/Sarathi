"""Anti-fabrication regression tests for Native Extraction capability telemetry.

Invariants verified:
1. Native extraction does not emit 1.0 quality confidence merely because parsing succeeded.
2. Pramana confidence is None unless supported by a measurable validation method.
3. Unusable native extraction escalated to OCR leaves behind no misleading quality observations.
"""

from __future__ import annotations

from pathlib import Path

from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    ExecutionContext,
    InputRef,
    Request,
)
from sarathi.shakti.native_extraction.capability import NativeExtractionCapability


def test_native_extraction_does_not_emit_100_percent_confidence(tmp_path: Path) -> None:
    """Proves native extraction emits confidence=None, not synthetic 1.0."""
    darpana = Darpana(capacity=50)
    cap = NativeExtractionCapability(darpana=darpana)

    txt_file = tmp_path / "valid_document.txt"
    txt_file.write_text("Valid text content for native extraction.\n", encoding="utf-8")

    inp = InputRef(
        input_id="inp-nat-1",
        source_path=txt_file,
        display_name="valid_document.txt",
        size_bytes=txt_file.stat().st_size,
    )
    req = Request(
        request_id="req-nat-1",
        requirement="read_native",
        inputs=(inp,),
    )
    ctx = ExecutionContext("run-nat-1", "req-nat-1", "t-1", "s-1")

    res = cap.execute(req, ctx)
    assert res.data is not None

    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) > 0
    for prec in pramana_recs:
        # Invariant: Never ConfidenceValue(score=1.0)
        assert prec.confidence is None, f"Expected confidence=None but got {prec.confidence}"
        assert prec.attributes.get("min_confidence") is None
        assert prec.attributes.get("max_confidence") is None


def test_unusable_native_extraction_leaves_no_misleading_quality_telemetry(tmp_path: Path) -> None:
    """Proves empty/unusable document that escalates to OCR does not record misleading quality observations."""
    darpana = Darpana(capacity=50)
    cap = NativeExtractionCapability(darpana=darpana)

    # Minimal valid PDF bytes that produce empty text
    empty_pdf = tmp_path / "empty_scanned.pdf"
    # Create empty valid PDF structure
    empty_pdf.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF\n")

    inp = InputRef(
        input_id="inp-nat-empty",
        source_path=empty_pdf,
        display_name="empty_scanned.pdf",
        size_bytes=empty_pdf.stat().st_size,
    )
    req = Request(
        request_id="req-nat-empty",
        requirement="read_native",
        inputs=(inp,),
    )
    ctx = ExecutionContext("run-nat-empty", "req-nat-empty", "t-2", "s-2")

    res = cap.execute(req, ctx)

    # Escalated to OCR
    assert any(w.code == "NATIVE_EXTRACTION_EMPTY" for w in res.warnings)

    # Invariant: No Pramana quality records emitted for unusable document
    pramana_recs = [r for r in darpana.pramana_records() if r.run_id == ctx.run_id]
    assert len(pramana_recs) == 0, f"Expected 0 quality records for empty escalated document, got {len(pramana_recs)}"
