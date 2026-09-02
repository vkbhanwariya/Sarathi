"""Comprehensive unit tests for Mukha Presenter, State, and Intake."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.darpana import Darpana, MarutiRecord, PramanaRecord
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.mukha import (
    AvailableActionView,
    InputSelectionView,
    MukhaPresenter,
    ProgressKind,
    ProgressState,
    WorkerPageView,
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
from sarathi.sankalpa import (
    ArtifactRef,
    ConfidenceValue,
    InputRef,
    Request,
    Result,
)


def _filter_run_telemetry(darpana: Darpana, run_id: str) -> tuple[tuple[MarutiRecord, ...], tuple[PramanaRecord, ...]]:
    maruti = tuple(r for r in darpana.maruti_records() if r.run_id == run_id)
    pramana = tuple(r for r in darpana.pramana_records() if r.run_id == run_id)
    return maruti, pramana


class TestMukhaComponents:
    """Tests for reusable formatting components."""

    @pytest.mark.parametrize(
        ("duration_ns", "expected"),
        [
            (None, "-"),
            (-100, "-"),
            (420_000_000, "0.42s"),
            (6_140_000_000, "06.1s"),
            (14_300_000_000, "14.3s"),
            (138_400_000_000, "02:18.4"),
        ],
    )
    def test_format_duration_ns(self, duration_ns: int | None, expected: str) -> None:
        assert format_duration_ns(duration_ns) == expected

    @pytest.mark.parametrize(
        ("size_bytes", "expected"),
        [
            (None, "-"),
            (-1, "-"),
            (500, "500 B"),
            (2048, "2.0 KB"),
            (5_242_880, "5.00 MB"),
            (2_147_483_648, "2.00 GB"),
        ],
    )
    def test_format_bytes(self, size_bytes: int | None, expected: str) -> None:
        assert format_bytes(size_bytes) == expected

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            (None, "-"),
            (0.958, "95.8%"),
            (0.894, "89.4%"),
            (1.0, "100.0%"),
        ],
    )
    def test_format_confidence(self, confidence: float | None, expected: str) -> None:
        assert format_confidence(confidence) == expected

    def test_status_badge(self) -> None:
        assert status_badge("running") == "RUNNING"
        assert status_badge("  success  ") == "SUCCESS"


class TestMukhaProgressStateContract:
    """Tests for strict ProgressState validation rules."""

    @pytest.mark.parametrize(
        ("completed", "total", "expected_pct"),
        [
            (5, 10, 50.0),
            (0, 10, 0.0),
            (10, 10, 100.0),
            (3, 4, 75.0),
        ],
    )
    def test_valid_known_progress(self, completed: int, total: int, expected_pct: float) -> None:
        prog = ProgressState.known(completed, total)
        assert prog.kind == ProgressKind.KNOWN
        assert prog.completed == completed
        assert prog.total == total
        assert prog.percentage == pytest.approx(expected_pct)

    @pytest.mark.parametrize(
        ("completed", "total"),
        [
            (3, 0),
            (5, -1),
            (-1, 10),
            (11, 10),
        ],
    )
    def test_invalid_known_progress_raises_value_error(self, completed: int, total: int) -> None:
        with pytest.raises(ValueError):
            ProgressState.known(completed, total)

    def test_indeterminate_and_unavailable_progress(self) -> None:
        indet = ProgressState.indeterminate(completed=4)
        assert indet.kind == ProgressKind.INDETERMINATE
        assert indet.completed == 4
        assert indet.percentage is None

        unavail = ProgressState.unavailable()
        assert unavail.kind == ProgressKind.UNAVAILABLE
        assert unavail.percentage is None


class TestMukhaInputAndIntakeTruth:
    """Tests for factual intake without suffix-as-content-truth."""

    def test_intake_from_paths_canonical_validation(self, tmp_path: Path) -> None:
        valid_f1 = tmp_path / "doc1.pdf"
        valid_f1.write_text("content1", encoding="utf-8")
        valid_f2 = tmp_path / "doc2.txt"
        valid_f2.write_text("content2", encoding="utf-8")
        missing_f = tmp_path / "missing.pdf"
        dir_f = tmp_path / "somedir"
        dir_f.mkdir()

        refs, sel, pf = MukhaPresenter.intake_from_paths([valid_f1, valid_f2, missing_f, dir_f, valid_f1])

        assert len(refs) == 2
        assert refs[0].display_name == "doc1.pdf"
        assert refs[0].size_bytes == valid_f1.stat().st_size
        assert refs[0].media_type is None
        assert refs[1].display_name == "doc2.txt"
        assert refs[1].size_bytes == valid_f2.stat().st_size

        assert pf.eligible_count == 2
        assert pf.issue_count == 3
        assert sel.is_grouped is False
        assert len(sel.groups) == 0

    def test_intake_from_paths_respects_kavacha_overlap_validation(self, tmp_path: Path) -> None:
        runtime_dir = tmp_path / "Runtime"
        output_dir = tmp_path / "Output"
        staged_file = runtime_dir / "staged.txt"
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        staged_file.write_text("staged", encoding="utf-8")

        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)

        with pytest.raises(DoshError) as exc_info:
            MukhaPresenter.intake_from_paths(
                [staged_file],
                kavacha=kavacha,
                runtime_root=runtime_dir,
                output_root=output_dir,
            )
        assert exc_info.value.code is FailureCode.SECURITY_DENIED

    def test_build_home_view_is_pure_projection(self) -> None:
        sel = InputSelectionView(total_files=2, total_size_bytes=1024, is_grouped=False)
        actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
        view = MukhaPresenter.build_home_view(
            input_selection=sel,
            requirement="read_native",
            policy_label="Local only",
            available_actions=actions,
        )
        assert view.current_screen == "home"
        assert view.requirement == "read_native"
        assert view.policy_label == "Local only"
        assert len(view.available_actions) == 1


class TestMukhaTelemetryAndRuntimeTruth:
    """Tests for real Darpana filtering, capability_execution-only device metrics, and monotonicity."""

    def test_real_darpana_run_scoped_filtering(self) -> None:
        darpana = Darpana(capacity=1000)
        darpana.record_maruti(
            MarutiRecord(
                run_id="run-A",
                request_id="req-A",
                trace_id="tr-A",
                span_id="sp-1",
                phase_name="capability_execution",
                component="yantra",
                duration_ns=300_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
                attributes={"device_type": "gpu"},
            )
        )
        darpana.record_maruti(
            MarutiRecord(
                run_id="run-B",
                request_id="req-B",
                trace_id="tr-B",
                span_id="sp-2",
                phase_name="capability_execution",
                component="yantra",
                duration_ns=800_000_000,
                timestamp_utc="2026-09-01T00:00:01Z",
                outcome="success",
                attributes={"device_type": "cpu"},
            )
        )

        darpana.record_pramana(
            PramanaRecord(
                run_id="run-A",
                request_id="req-A",
                trace_id="tr-A",
                span_id="sp-1",
                capability_id="ocr",
                stage="ocr",
                timestamp_utc="2026-09-01T00:00:00Z",
                confidence=ConfidenceValue(score=0.97, method="test", evidence={"test": True}),
                attributes={"device_type": "gpu"},
            )
        )

        maruti_a, pramana_a = _filter_run_telemetry(darpana, "run-A")
        assert len(maruti_a) == 1
        assert maruti_a[0].run_id == "run-A"
        assert len(pramana_a) == 1
        assert pramana_a[0].run_id == "run-A"

        maruti_b, pramana_b = _filter_run_telemetry(darpana, "run-B")
        assert len(maruti_b) == 1
        assert maruti_b[0].run_id == "run-B"
        assert len(pramana_b) == 0

    def test_device_telemetry_aggregates_only_capability_execution_spans(self) -> None:
        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp1",
                phase_name="allocation",
                component="yantra",
                duration_ns=10_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
                attributes={"device_type": "gpu"},
            ),
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp2",
                phase_name="capability_execution",
                component="yantra",
                duration_ns=500_000_000,
                timestamp_utc="2026-09-01T00:00:01Z",
                outcome="success",
                attributes={"device_type": "gpu"},
            ),
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp3",
                phase_name="release",
                component="yantra",
                duration_ns=5_000_000,
                timestamp_utc="2026-09-01T00:00:02Z",
                outcome="success",
                attributes={"device_type": "gpu"},
            ),
        ]

        state = MukhaPresenter.build_monitor_view(
            run_id="run-102",
            status="running",
            started_at_ns=0,
            now_ns=1_000_000_000,
            files=(),
            maruti_records=maruti_recs,
        )

        assert len(state.device_progress) == 1
        gpu_stat = state.device_progress[0]
        assert gpu_stat.device_type == "GPU"
        assert gpu_stat.execution_count == 1
        assert gpu_stat.total_duration_ns == 500_000_000

    def test_five_second_rule_for_long_running_operations(self) -> None:
        workers = [
            WorkerPageView(
                worker_id="w-1", file_display_name="fast.pdf", stage="OCR", device_type="GPU", elapsed_ns=2_000_000_000
            ),
            WorkerPageView(
                worker_id="w-2",
                file_display_name="slow.pdf",
                stage="Inference",
                device_type="CPU",
                elapsed_ns=8_000_000_000,
            ),
        ]

        state = MukhaPresenter.build_monitor_view(
            run_id="run-101",
            status="running",
            started_at_ns=0,
            now_ns=10_000_000_000,
            files=(),
            active_workers=workers,
        )

        assert len(state.long_running) == 1
        assert state.long_running[0].operation_name == "Worker w-2 - slow.pdf"
        assert state.long_running[0].is_long_running is True

    def test_terminal_state_monotonicity_prevents_regression(self) -> None:
        initial = MukhaPresenter.build_monitor_view(
            run_id="run-103",
            status="SUCCESS",
            started_at_ns=0,
            now_ns=5_000_000_000,
            files=(),
        )
        assert initial.status == "SUCCESS"

        updated = MukhaPresenter.build_monitor_view(
            run_id="run-103",
            status="running",
            started_at_ns=0,
            now_ns=6_000_000_000,
            files=(),
            current_state=initial,
        )
        assert updated.status == "SUCCESS"


class TestMukhaSummaryAndArtifactsTruth:
    """Tests for Screen 4: Samapti - Run Summary and artifact confirmation truth."""

    def test_summary_uses_canonical_parameters_not_span_failure_counts(self, tmp_path: Path) -> None:
        art_file = tmp_path / "confirmed.pdf"
        art_file.write_text("pdf_out", encoding="utf-8")

        req = Request(
            request_id="req-201",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=tmp_path / "in.pdf",
                    display_name="in.pdf",
                    size_bytes=100,
                ),
            ),
        )

        res = Result(
            data="text",
            artifacts=(
                ArtifactRef(
                    artifact_id="art-1",
                    role="text_export",
                    media_type="application/pdf",
                    path=art_file,
                    size_bytes=7,
                    checksum_sha256="1234567890abcdef",
                ),
            ),
            confidence=ConfidenceValue(score=0.96, method="test", evidence={"test": True}),
        )

        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req-201",
                trace_id="tr1",
                span_id="sp1",
                phase_name="capability_execution",
                component="nabhi.pravaha",
                duration_ns=400_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="failure",
                attributes={"device_type": "cpu"},
            ),
            MarutiRecord(
                run_id="r1",
                request_id="req-201",
                trace_id="tr1",
                span_id="sp2",
                phase_name="capability_execution",
                component="nabhi.pravaha",
                duration_ns=600_000_000,
                timestamp_utc="2026-09-01T00:00:01Z",
                outcome="success",
                attributes={"device_type": "cpu"},
            ),
        ]

        summary = MukhaPresenter.build_summary_view(
            run_id="req-201",
            status="SUCCESS",
            wall_time_ns=1_000_000_000,
            request=req,
            result=res,
            successful_files=1,
            warning_files=0,
            failed_files=0,
            quarantined_count=0,
            retry_count=1,
            maruti_records=maruti_recs,
        )

        assert summary.status == "SUCCESS"
        assert summary.wall_time_ns == 1_000_000_000
        assert summary.successful_files == 1
        assert summary.failed_files == 0
        assert summary.retry_count == 1
        assert len(summary.artifacts) == 1
        assert summary.artifacts[0].display_name == "confirmed.pdf"
        assert summary.accuracy is None

    def test_artifact_intent_is_not_displayed_as_confirmed_artifact(self, tmp_path: Path) -> None:
        in_file = tmp_path / "in.txt"
        in_file.write_text("in", encoding="utf-8")
        req = Request(
            request_id="req-202",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=in_file,
                    display_name="in.txt",
                    size_bytes=2,
                ),
            ),
        )
        res = Result(
            data="text",
            artifacts=(),
        )

        summary = MukhaPresenter.build_summary_view(
            run_id="req-202",
            status="SUCCESS",
            wall_time_ns=500_000_000,
            request=req,
            result=res,
            successful_files=1,
            warning_files=0,
            failed_files=0,
        )

        assert len(summary.artifacts) == 0

    def test_monitor_view_terminal_status_casing_resilient(self) -> None:
        """Terminal file counting and status sticky logic is resilient to casing differences."""
        from sarathi.mukha.state import FileRunView, RunViewState

        files = [
            FileRunView(input_id="f1", display_name="f1.pdf", ordinal=1, status="success", elapsed_ns=10, current_stage="done"),
            FileRunView(input_id="f2", display_name="f2.pdf", ordinal=2, status="SUCCESS", elapsed_ns=10, current_stage="done"),
            FileRunView(input_id="f3", display_name="f3.pdf", ordinal=3, status="Completed", elapsed_ns=10, current_stage="done"),
            FileRunView(input_id="f4", display_name="f4.pdf", ordinal=4, status="FAILED", elapsed_ns=10, current_stage="err"),
            FileRunView(input_id="f5", display_name="f5.pdf", ordinal=5, status="running", elapsed_ns=10, current_stage="ocr"),
        ]

        # Prior terminal state
        prev_state = RunViewState(
            run_id="run-1",
            status="completed",
            elapsed_ns=1000,
            terminal_files=3,
            total_files=5,
            current_focus=None,
            files=(),
            active_workers=(),
            device_progress=(),
            long_running=(),
        )

        monitor = MukhaPresenter.build_monitor_view(
            run_id="run-1",
            status="in_progress",
            started_at_ns=0,
            now_ns=1000,
            files=files,
            current_state=prev_state,
        )

        # 4 files are terminal (f1, f2, f3, f4), f5 is running
        assert monitor.terminal_files == 4
        # Since prev_state was "completed" (terminal), effective_status is sticky
        assert monitor.status == "completed"
