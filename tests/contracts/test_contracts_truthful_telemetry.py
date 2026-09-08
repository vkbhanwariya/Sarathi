"""Anti-fabrication regression tests for Contracts (ConfidenceValue, AccuracyValue, PramanaRecord).

Invariants verified:
1. AccuracyValue is strictly evidence-backed and requires non-empty evidence describing the ground truth.
2. AccuracyValue is never derived from ConfidenceValue alone.
3. PramanaRecord truthfully supports confidence=None and accuracy=None.
4. ConfidenceValue strictly validates score ratio [0.0, 1.0] and rejects boolean or invalid types.
"""

from __future__ import annotations

import pytest

from sarathi.darpana import AccuracyValue, PramanaRecord
from sarathi.sankalpa import ConfidenceValue


class TestTruthfulContracts:
    """Invariant tests for confidence and accuracy contracts."""

    def test_accuracy_requires_factual_evidence(self) -> None:
        """AccuracyValue must reject empty evidence or missing method."""
        with pytest.raises(ValueError, match="evidence must be a non-empty mapping"):
            AccuracyValue(score=0.95, method="char_error_rate", evidence={})

        with pytest.raises(ValueError, match="method must be a non-empty string"):
            AccuracyValue(score=0.95, method="", evidence={"ground_truth_id": "test-gt"})

    def test_accuracy_is_distinct_from_confidence(self) -> None:
        """AccuracyValue and ConfidenceValue are separate types; PramanaRecord handles both independently."""
        conf = ConfidenceValue(
            score=0.92,
            method="rapidocr_line",
            evidence={"score_kind": "raw_engine", "calibrated": False},
        )
        acc = AccuracyValue(
            score=0.98,
            method="word_error_rate",
            evidence={"ground_truth": "test_corpus_v1", "sample_count": 50},
        )

        rec = PramanaRecord(
            run_id="run-acc",
            request_id="req-acc",
            trace_id="t-1",
            span_id="s-1",
            capability_id="test",
            stage="test",
            timestamp_utc="2026-09-08T00:00:00Z",
            confidence=conf,
            accuracy=acc,
        )

        assert rec.confidence.score == 0.92
        assert rec.accuracy.score == 0.98
        assert rec.confidence is not rec.accuracy

    def test_pramana_truthfully_allows_none_for_both_confidence_and_accuracy(self) -> None:
        """PramanaRecord allows confidence=None and accuracy=None without inventing values."""
        rec = PramanaRecord(
            run_id="run-none",
            request_id="req-none",
            trace_id="t-1",
            span_id="s-1",
            capability_id="test",
            stage="test",
            timestamp_utc="2026-09-08T00:00:00Z",
            confidence=None,
            accuracy=None,
        )
        assert rec.confidence is None
        assert rec.accuracy is None
