"""Unit tests for Darpana — Telemetry & Tracing Phase 1."""

from pathlib import Path
import pytest

from sarathi.darpana import (
    AccuracyValue,
    Darpana,
    MarutiRecord,
    PramanaRecord,
)
import sarathi.darpana as darpana_module
from sarathi.sankalpa import ConfidenceValue, ExecutionContext


@pytest.fixture
def execution_context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-001",
        request_id="req-001",
        trace_id="trace-001",
        span_id="span-001",
    )


class TestMarutiTelemetry:
    def test_maruti_record_immutability_and_attributes(self) -> None:
        rec = MarutiRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            phase_name="read",
            component="shakti.native_extraction",
            timestamp_utc="2026-09-01T00:00:00Z",
            duration_ns=1500000,
            outcome="success",
            attributes={"pages": 3},
        )
        assert rec.run_id == "run-1"
        assert rec.duration_ns == 1500000
        assert rec.outcome == "success"
        assert rec.attributes["pages"] == 3

        with pytest.raises(TypeError):
            rec.attributes["pages"] = 4  # type: ignore

    def test_maruti_record_validation(self) -> None:
        with pytest.raises(ValueError, match="phase_name must be a non-empty string"):
            MarutiRecord(
                run_id="r",
                request_id="req",
                trace_id="t",
                span_id="s",
                phase_name="",
                component="comp",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="success",
            )

        with pytest.raises(TypeError, match="duration_ns must be an integer"):
            MarutiRecord(
                run_id="r",
                request_id="req",
                trace_id="t",
                span_id="s",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=True,  # type: ignore
                outcome="success",
            )

        with pytest.raises(ValueError, match="duration_ns cannot be negative"):
            MarutiRecord(
                run_id="r",
                request_id="req",
                trace_id="t",
                span_id="s",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=-50,
                outcome="success",
            )

        with pytest.raises(ValueError, match="outcome must be 'success' or 'failure'"):
            MarutiRecord(
                run_id="r",
                request_id="req",
                trace_id="t",
                span_id="s",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="partial",
            )

    def test_time_scope_success(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with darpana.time_scope(
            execution_context,
            phase_name="extract",
            component="shakti.native_extraction",
            attributes={"format": "pdf"},
        ):
            # simulate work
            _ = sum(range(1000))

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.run_id == "run-001"
        assert rec.request_id == "req-001"
        assert rec.trace_id == "trace-001"
        assert rec.span_id == "span-001"
        assert rec.phase_name == "extract"
        assert rec.component == "shakti.native_extraction"
        assert rec.outcome == "success"
        assert rec.error_type is None
        assert rec.duration_ns >= 0
        assert rec.attributes["format"] == "pdf"

    def test_time_scope_failure_and_privacy(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with pytest.raises(ValueError, match="Confidential sensitive error details"):
            with darpana.time_scope(
                execution_context,
                phase_name="ocr",
                component="shakti.ocr",
            ):
                raise ValueError("Confidential sensitive error details")

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "ValueError"
        assert rec.duration_ns >= 0
        # Privacy check: sensitive message is not recorded in error_type or attributes
        assert "Confidential sensitive error details" not in rec.error_type
        assert "Confidential sensitive error details" not in str(rec.attributes)

    def test_time_scope_records_keyboard_interrupt_and_reraises(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with pytest.raises(KeyboardInterrupt):
            with darpana.time_scope(
                execution_context,
                phase_name="process",
                component="shakti.bank_statements",
            ):
                raise KeyboardInterrupt()

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "KeyboardInterrupt"
        assert rec.duration_ns >= 0

    def test_time_scope_validates_before_executing_wrapped_work(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)
        executed = False

        # Invalid attributes type must raise TypeError before entering work block
        with pytest.raises(TypeError, match="attributes must be a Mapping or None"):
            with darpana.time_scope(
                execution_context,
                phase_name="extract",
                component="shakti.native_extraction",
                attributes="invalid_string_attributes",  # type: ignore
            ):
                executed = True

        assert executed is False
        assert len(darpana.maruti_records()) == 0

        # Invalid empty phase_name
        with pytest.raises(ValueError, match="phase_name must be a non-empty string"):
            with darpana.time_scope(
                execution_context,
                phase_name="  ",
                component="comp",
            ):
                executed = True

        assert executed is False
        assert len(darpana.maruti_records()) == 0


class TestPramanaTelemetry:
    def test_accuracy_value_ratio_and_evidence(self) -> None:
        acc = AccuracyValue(
            score=0.92,
            method="ground_truth_cer_levenshtein",
            evidence={"evaluated_chars": 1500, "errors": 120},
        )
        assert acc.score == 0.92
        assert acc.as_ratio == 0.92
        assert acc.as_percent == 92.0
        assert acc.method == "ground_truth_cer_levenshtein"
        assert acc.evidence["evaluated_chars"] == 1500

        with pytest.raises(TypeError):
            acc.evidence["errors"] = 0  # type: ignore

    def test_accuracy_value_validation(self) -> None:
        with pytest.raises(TypeError, match="cannot be a boolean"):
            AccuracyValue(score=True, method="cer", evidence={"n": 1})

        with pytest.raises(TypeError, match="must be numeric"):
            AccuracyValue(score="0.9", method="cer", evidence={"n": 1})  # type: ignore

        with pytest.raises(ValueError, match="cannot be NaN or Inf"):
            AccuracyValue(score=float("nan"), method="cer", evidence={"n": 1})

        with pytest.raises(ValueError, match="ratio in range"):
            AccuracyValue(score=92.0, method="cer", evidence={"n": 1})

        with pytest.raises(ValueError, match="ratio in range"):
            AccuracyValue(score=-0.01, method="cer", evidence={"n": 1})

        with pytest.raises(ValueError, match="non-empty string"):
            AccuracyValue(score=0.9, method="   ", evidence={"n": 1})

        with pytest.raises(ValueError, match="non-empty mapping"):
            AccuracyValue(score=0.9, method="cer", evidence={})

    def test_pramana_record_with_confidence_and_accuracy(self) -> None:
        conf = ConfidenceValue(
            score=0.95,
            method="ocr_char_probabilities",
            evidence={"min": 0.8},
        )
        acc = AccuracyValue(
            score=0.98,
            method="exact_cell_comparison",
            evidence={"cells": 100},
        )
        rec = PramanaRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="ocr",
            stage="page_recognition",
            timestamp_utc="2026-09-01T00:00:00Z",
            subject_id="page_1",
            confidence=conf,
            accuracy=acc,
            attributes={"lang": "hi"},
        )
        assert rec.capability_id == "ocr"
        assert rec.confidence == conf
        assert rec.accuracy == acc
        assert rec.subject_id == "page_1"

    def test_pramana_record_unavailable_defaults_stay_none(self) -> None:
        rec = PramanaRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="darshana",
            stage="identify",
            timestamp_utc="2026-09-01T00:00:00Z",
        )
        assert rec.confidence is None
        assert rec.accuracy is None
        assert rec.subject_id is None


class TestDarpanaService:
    def test_bounded_history_eviction(self) -> None:
        darpana = Darpana(capacity=3)
        assert darpana.capacity == 3

        for i in range(5):
            rec = MarutiRecord(
                run_id=f"run-{i}",
                request_id="req",
                trace_id="tr",
                span_id="sp",
                phase_name="test",
                component="comp",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="success",
            )
            darpana.record_maruti(rec)

        records = darpana.maruti_records()
        assert len(records) == 3
        # Oldest 0, 1 evicted, remaining are 2, 3, 4
        assert [r.run_id for r in records] == ["run-2", "run-3", "run-4"]
        assert isinstance(records, tuple)

    def test_darpana_pramana_recording_and_snapshot(self) -> None:
        darpana = Darpana(capacity=5)
        rec = PramanaRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="ocr",
            stage="read",
            timestamp_utc="2026-09-01T00:00:00Z",
        )
        darpana.record_pramana(rec)

        pramana_recs = darpana.pramana_records()
        assert len(pramana_recs) == 1
        assert pramana_recs[0] == rec
        assert isinstance(pramana_recs, tuple)

    def test_darpana_explicit_capacity_required(self) -> None:
        # Default capacity removed: constructor must reject no arguments
        with pytest.raises(TypeError):
            Darpana()  # type: ignore

        with pytest.raises(TypeError, match="capacity must be an integer"):
            Darpana(capacity="100")  # type: ignore

        with pytest.raises(ValueError, match="capacity must be a positive integer"):
            Darpana(capacity=0)

    def test_darpana_exports(self) -> None:
        expected = {"AccuracyValue", "Darpana", "MarutiRecord", "PramanaRecord"}
        assert set(darpana_module.__all__) == expected
        for name in expected:
            assert hasattr(darpana_module, name)
