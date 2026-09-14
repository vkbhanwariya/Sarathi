"""Anti-fabrication regression tests for Mukha telemetry presentation.

Invariants verified:
1. confidence=None through Pramana -> Mukha inspector preserves confidence_score=None.
2. Missing page/region confidence does not become 1.0.
3. Missing page confidence does not enter any confidence distribution bucket.
4. Missing min_confidence / max_confidence remain None instead of 1.0.
5. format_confidence(None) formats truthfully as '-'.
6. Run-level confidence page-weights only groups that actually emit page observations.
"""

from __future__ import annotations

from pathlib import Path

from sarathi.darpana import PramanaRecord
from sarathi.mukha.presenter import MukhaPresenter, format_confidence
from sarathi.mukha.state import InspectorViewState, PageConfidenceView, RegionConfidenceView
from sarathi.sankalpa import ConfidenceValue, InputRef, Request


class TestMukhaTruthfulTelemetry:
    """Anti-fabrication regression tests for Mukha presentation layer."""

    def test_mukha_truthful_none_confidence_preservation(self) -> None:
        """Verify confidence=None in Pramana records remains None in PageConfidenceView and RegionConfidenceView."""
        pramana = (
            PramanaRecord(
                run_id="run-none",
                request_id="req-none",
                trace_id="tr-1",
                span_id="sp-1",
                capability_id="ocr",
                stage="ocr",
                timestamp_utc="2026-09-08T00:00:00Z",
                subject_id="doc-1:p1",
                confidence=None,
                attributes={
                    "level": "page",
                    "page_number": 1,
                    "file_display_name": "sample.pdf",
                    "region_count": 0,
                    "min_confidence": None,
                    "max_confidence": None,
                },
            ),
            PramanaRecord(
                run_id="run-none",
                request_id="req-none",
                trace_id="tr-1",
                span_id="sp-2",
                capability_id="ocr",
                stage="ocr",
                timestamp_utc="2026-09-08T00:00:00Z",
                subject_id="doc-1:p1:r0",
                confidence=None,
                attributes={
                    "level": "region",
                    "region_id": "p1_line_1",
                    "page_number": 1,
                    "file_display_name": "sample.pdf",
                    "region_type": "line",
                },
            ),
        )

        inspector = MukhaPresenter.build_inspector_view(
            run_id="run-none",
            status="COMPLETED",
            elapsed_ns=10_000_000,
            maruti_records=(),
            pramana_records=pramana,
        )

        assert isinstance(inspector, InspectorViewState)
        assert len(inspector.page_confidence) == 1
        page_view: PageConfidenceView = inspector.page_confidence[0]
        # Invariant: Never 1.0 or 100% when score is missing
        assert page_view.confidence_score is None
        assert page_view.min_confidence is None
        assert page_view.max_confidence is None

        assert len(inspector.region_confidence) == 1
        reg_view: RegionConfidenceView = inspector.region_confidence[0]
        assert reg_view.confidence_score is None

    def test_missing_confidence_does_not_enter_distribution_buckets(self) -> None:
        """Verify that Pramana records with confidence=None do NOT contribute to confidence brackets."""
        pramana = (
            PramanaRecord(
                run_id="run-bucket-check",
                request_id="req-bucket-check",
                trace_id="tr-1",
                span_id="sp-1",
                capability_id="translation",
                stage="translation",
                timestamp_utc="2026-09-08T00:00:00Z",
                subject_id="doc-1:p1",
                confidence=None,
                attributes={"level": "page", "page_number": 1},
            ),
            PramanaRecord(
                run_id="run-bucket-check",
                request_id="req-bucket-check",
                trace_id="tr-1",
                span_id="sp-2",
                capability_id="translation",
                stage="translation",
                timestamp_utc="2026-09-08T00:00:00Z",
                subject_id="doc-1:p1:s0",
                confidence=None,
                attributes={"level": "region", "region_id": "r1"},
            ),
        )

        inspector = MukhaPresenter.build_inspector_view(
            run_id="run-bucket-check",
            status="COMPLETED",
            elapsed_ns=10_000_000,
            maruti_records=(),
            pramana_records=pramana,
        )

        dist = dict(inspector.confidence_distribution)
        assert dist["90-100%"] == 0
        assert dist["75-89%"] == 0
        assert dist["50-74%"] == 0
        assert dist["<50%"] == 0

    def test_summary_confidence_page_weights_only_matching_group(self) -> None:
        """OCR region density must not erase an unrelated capability's measured confidence."""
        request = Request(
            request_id="req-page-weight",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="input-page-weight",
                    source_path=Path("input.pdf"),
                    display_name="input.pdf",
                    size_bytes=1,
                ),
            ),
        )
        page = PramanaRecord(
            run_id="run-page-weight",
            request_id=request.request_id,
            trace_id="tr-page-weight",
            span_id="sp-page",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-08T00:00:00Z",
            confidence=ConfidenceValue(score=0.8, method="test", evidence={"level": "page"}),
            attributes={"level": "page"},
        )
        region = PramanaRecord(
            run_id="run-page-weight",
            request_id=request.request_id,
            trace_id="tr-page-weight",
            span_id="sp-region",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-08T00:00:00Z",
            confidence=ConfidenceValue(score=0.2, method="test", evidence={"level": "region"}),
            attributes={"level": "region"},
        )
        translation = PramanaRecord(
            run_id="run-page-weight",
            request_id=request.request_id,
            trace_id="tr-page-weight",
            span_id="sp-translation",
            capability_id="translation",
            stage="translation",
            timestamp_utc="2026-09-08T00:00:00Z",
            confidence=ConfidenceValue(score=0.6, method="test", evidence={"level": "document"}),
        )

        summary = MukhaPresenter.build_summary_view(
            run_id="run-page-weight",
            status="COMPLETED",
            wall_time_ns=1_000_000,
            request=request,
            pramana_records=(page, region, translation),
        )

        assert summary.avg_confidence == 0.7

    def test_format_confidence_preserves_none(self) -> None:
        """format_confidence must return '-' for None, never '100.0%' or '0.0%'."""
        assert format_confidence(None) == "-"
        assert format_confidence(0.95) == "95.0%"
        assert format_confidence(1.0) == "100.0%"
