"""Unit tests for Mukha - Console & Presentation Phase 1."""

from pathlib import Path
import pytest

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.kavacha import SecurityPolicy
from sarathi.mukha import (
    ApplicationViewState,
    ConsoleRenderer,
    FileRunView,
    MukhaPresenter,
    OperationView,
    ProgressKind,
    RunSummaryView,
    RunViewState,
    WorkerPageView,
    format_bytes,
    format_confidence,
    format_duration_ns,
    format_table,
)
from sarathi.nabhi.quarantine import QuarantineRecord, QuarantineStatus
from sarathi.sankalpa import (
    ArtifactRef,
    ConfidenceValue,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
    WarningRecord,
)


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

    def test_format_table(self) -> None:
        table = format_table(["Name", "Score"], [["Alice", "95%"], ["Bob", "88%"]])
        assert "Name" in table
        assert "Alice" in table
        assert "Bob" in table


class TestMukhaHomeFlow:
    """Tests for Screen 1: Griha - Home & Input Setup flow."""

    def test_individual_listing_for_small_batches(self, tmp_path: Path) -> None:
        files = []
        for i in range(5):
            f = tmp_path / f"doc_{i}.pdf"
            f.write_text("dummy", encoding="utf-8")
            files.append(f)

        state = MukhaPresenter.build_home_view(files, requirement="read_native")
        assert state.input_selection.total_files == 5
        assert not state.input_selection.is_grouped
        assert len(state.input_selection.items) == 5
        assert state.preflight is not None
        assert state.preflight.eligible_count == 5
        assert state.preflight.issue_count == 0

        rendered = ConsoleRenderer.render_home(state)
        assert "5 files selected" in rendered
        assert "doc_0.pdf" in rendered

    def test_compact_grouping_for_large_batches(self, tmp_path: Path) -> None:
        files = []
        # Create 12 PDF files and 3 XLSX files (>10 total files)
        for i in range(12):
            f = tmp_path / f"pdf_{i}.pdf"
            f.write_text("pdf_content", encoding="utf-8")
            files.append(f)
        for i in range(3):
            f = tmp_path / f"sheet_{i}.xlsx"
            f.write_text("sheet_content", encoding="utf-8")
            files.append(f)

        state = MukhaPresenter.build_home_view(files, requirement="read_native")
        assert state.input_selection.total_files == 15
        assert state.input_selection.is_grouped
        assert len(state.input_selection.groups) == 2

        rendered = ConsoleRenderer.render_home(state)
        assert "15 files selected" in rendered
        assert "PDF" in rendered
        assert "XLSX" in rendered

    def test_preflight_identifies_missing_and_directory_issues(self, tmp_path: Path) -> None:
        valid_file = tmp_path / "valid.txt"
        valid_file.write_text("content", encoding="utf-8")
        missing_file = tmp_path / "missing.txt"
        dir_file = tmp_path / "somedir"
        dir_file.mkdir()

        state = MukhaPresenter.build_home_view([valid_file, missing_file, dir_file])
        assert state.preflight is not None
        assert state.preflight.eligible_count == 1
        assert state.preflight.issue_count == 2

        rendered = ConsoleRenderer.render_home(state)
        assert "1 eligible | 2 issues" in rendered


class TestMukhaMonitorFlow:
    """Tests for Screen 2: Pravritti - Live Run Monitor."""

    def test_five_second_rule_promotes_long_running_operations(self) -> None:
        workers = [
            WorkerPageView(
                worker_id="w-1",
                file_display_name="fast_doc.pdf",
                stage="OCR",
                device_type="GPU",
                elapsed_ns=2_000_000_000,  # 2.0s (<5s, NOT long running)
            ),
            WorkerPageView(
                worker_id="w-2",
                file_display_name="slow_doc.pdf",
                stage="Inference",
                device_type="CPU",
                elapsed_ns=8_300_000_000,  # 8.3s (>=5s, IS long running)
            ),
        ]

        state = MukhaPresenter.build_monitor_view(
            run_id="run-001",
            status="running",
            started_at_ns=0,
            now_ns=10_000_000_000,
            files=(),
            active_workers=workers,
        )

        assert len(state.long_running) == 1
        assert state.long_running[0].operation_name == "Worker w-2 - slow_doc.pdf"
        assert state.long_running[0].is_long_running is True

        rendered = ConsoleRenderer.render_monitor(state)
        assert "Long-running Operations (>5s):" in rendered
        assert "slow_doc.pdf" in rendered

    def test_device_progress_aggregated_from_real_records(self) -> None:
        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp1",
                phase_name="ocr",
                component="yantra",
                duration_ns=340_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
                attributes={"device_type": "gpu"},
            ),
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp2",
                phase_name="ocr",
                component="yantra",
                duration_ns=1_180_000_000,
                timestamp_utc="2026-09-01T00:00:01Z",
                outcome="success",
                attributes={"device_type": "cpu"},
            ),
        ]

        pramana_recs = [
            PramanaRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp1",
                capability_id="ocr",
                stage="ocr",
                timestamp_utc="2026-09-01T00:00:00Z",
                confidence=ConfidenceValue(score=0.958, method="test", evidence={"test": True}),
                attributes={"device_type": "gpu"},
            ),
            PramanaRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp2",
                capability_id="ocr",
                stage="ocr",
                timestamp_utc="2026-09-01T00:00:01Z",
                confidence=ConfidenceValue(score=0.897, method="test", evidence={"test": True}),
                attributes={"device_type": "cpu"},
            ),
        ]

        state = MukhaPresenter.build_monitor_view(
            run_id="run-002",
            status="running",
            started_at_ns=0,
            now_ns=5_000_000_000,
            files=(),
            maruti_records=maruti_recs,
            pramana_records=pramana_recs,
        )

        assert len(state.device_progress) == 2
        gpu_prog = next(p for p in state.device_progress if p.device_type == "GPU")
        cpu_prog = next(p for p in state.device_progress if p.device_type == "CPU")

        assert gpu_prog.units_processed == 1
        assert gpu_prog.avg_confidence == pytest.approx(0.958)
        assert cpu_prog.units_processed == 1
        assert cpu_prog.avg_confidence == pytest.approx(0.897)

        # NPU was not in telemetry records, so it must not exist in device_progress
        assert all(p.device_type != "NPU" for p in state.device_progress)

        rendered = ConsoleRenderer.render_monitor(state)
        assert "GPU" in rendered
        assert "CPU" in rendered
        assert "NPU" not in rendered


class TestMukhaSummaryAndInspectorFlow:
    """Tests for Screen 4: Samapti - Run Summary and Screen 5: Nirikshana - Run Inspector."""

    def test_run_summary_factual_aggregation(self, tmp_path: Path) -> None:
        art_path = tmp_path / "out.txt"
        art_path.write_text("result", encoding="utf-8")

        req = Request(
            request_id="req-summary-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=tmp_path / "in.txt",
                    display_name="in.txt",
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
                    media_type="text/plain",
                    path=art_path,
                    size_bytes=6,
                    checksum_sha256="abcdef1234567890",
                ),
            ),
            confidence=ConfidenceValue(score=0.965, method="test", evidence={"test": True}),
            warnings=(WarningRecord(code="TEXT_WARNING", stage="read_native", message="Non-critical text warning"),),
        )

        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req-summary-1",
                trace_id="tr1",
                span_id="sp1",
                phase_name="pipeline_stage",
                component="nabhi.pravaha",
                duration_ns=1_200_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
                attributes={"device_type": "cpu"},
            ),
        ]

        summary = MukhaPresenter.build_summary_view(
            run_id="run-summary-001",
            request=req,
            result=res,
            maruti_records=maruti_recs,
        )

        assert summary.run_id == "run-summary-001"
        assert summary.status == "SUCCESS"
        assert summary.wall_time_ns == 1_200_000_000
        assert summary.total_inputs == 1
        assert summary.successful_files == 1
        assert summary.warning_files == 1
        assert len(summary.artifacts) == 1
        assert summary.artifacts[0].display_name == "out.txt"
        assert summary.accuracy is None  # Accuracy is unavailable without ground truth

        rendered = ConsoleRenderer.render_summary(summary)
        assert "Samapti - Run Summary" in rendered
        assert "SUCCESS" in rendered
        assert "out.txt" in rendered
        assert "Verified Accuracy: unavailable (no reference corpus)" in rendered

    def test_inspector_tabs_render(self) -> None:
        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp1",
                phase_name="resolution",
                component="nabhi.manthan",
                duration_ns=450_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
            ),
        ]

        inspector_state = MukhaPresenter.build_inspector_view(
            run_id="run-insp-001",
            status="success",
            elapsed_ns=450_000_000,
            maruti_records=maruti_recs,
        )

        # Render Activity tab
        act_rendered = ConsoleRenderer.render_inspector(inspector_state, tab="activity")
        assert "Activity Log:" in act_rendered
        assert "nabhi.manthan" in act_rendered

        # Render Performance tab
        perf_rendered = ConsoleRenderer.render_inspector(inspector_state, tab="performance")
        assert "Performance Details:" in perf_rendered
        assert "resolution" in perf_rendered

        # Render System tab
        sys_rendered = ConsoleRenderer.render_inspector(inspector_state, tab="system")
        assert "System Facts:" in sys_rendered
        assert "Total Maruti Records" in sys_rendered
