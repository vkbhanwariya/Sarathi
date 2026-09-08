"""Anti-fabrication regression tests for Mukha telemetry presentation.

Invariants verified:
1. confidence=None through Pramana -> Mukha inspector preserves confidence_score=None.
2. Missing page/region confidence does not become 1.0.
3. Missing page confidence does not enter any confidence distribution bucket.
4. Missing min_confidence / max_confidence remain None instead of 1.0.
5. format_confidence(None) formats truthfully as '-'.
"""

from __future__ import annotations

from sarathi.darpana import PramanaRecord
from sarathi.mukha.presenter import MukhaPresenter, format_confidence
from sarathi.mukha.state import InspectorViewState, PageConfidenceView, RegionConfidenceView


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

    def test_format_confidence_preserves_none(self) -> None:
        """format_confidence must return '-' for None, never '100.0%' or '0.0%'."""
        assert format_confidence(None) == "-"
        assert format_confidence(0.95) == "95.0%"
        assert format_confidence(1.0) == "100.0%"
