"""Comprehensive unit and headless Textual tests for Mukha - Console & Presentation."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.mukha import (
    ApplicationViewState,
    AvailableActionView,
    FileRunView,
    HomeScreen,
    InputGroupView,
    InputItemView,
    InputSelectionView,
    InspectorScreen,
    InspectorViewState,
    MonitorScreen,
    MukhaApp,
    MukhaPresenter,
    OperationView,
    PreflightView,
    ProgressKind,
    ProgressState,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    SummaryScreen,
    WorkerPageView,
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
from sarathi.sankalpa import (
    ArtifactIntent,
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

    def test_status_badge(self) -> None:
        assert status_badge("running") == "RUNNING"
        assert status_badge("  success  ") == "SUCCESS"


class TestMukhaInputAndIntakeTruth:
    """Tests for factual intake and presenter input views."""

    def test_intake_from_paths_canonical_validation(self, tmp_path: Path) -> None:
        valid_f1 = tmp_path / "doc1.pdf"
        valid_f1.write_text("content1", encoding="utf-8")
        valid_f2 = tmp_path / "doc2.txt"
        valid_f2.write_text("content2", encoding="utf-8")
        missing_f = tmp_path / "missing.pdf"
        dir_f = tmp_path / "somedir"
        dir_f.mkdir()

        refs, sel, pf = MukhaPresenter.intake_from_paths(
            [valid_f1, valid_f2, missing_f, dir_f, valid_f1]
        )

        assert len(refs) == 2
        assert refs[0].display_name == "doc1.pdf"
        assert refs[0].size_bytes == valid_f1.stat().st_size
        assert refs[1].display_name == "doc2.txt"
        assert refs[1].size_bytes == valid_f2.stat().st_size

        assert pf.eligible_count == 2
        assert pf.issue_count == 3
        assert not sel.is_grouped

    def test_intake_from_paths_large_batch_grouping(self, tmp_path: Path) -> None:
        files = []
        for i in range(12):
            f = tmp_path / f"pdf_{i}.pdf"
            f.write_text("pdf_data", encoding="utf-8")
            files.append(f)
        for i in range(3):
            f = tmp_path / f"sheet_{i}.xlsx"
            f.write_text("sheet_data", encoding="utf-8")
            files.append(f)

        refs, sel, pf = MukhaPresenter.intake_from_paths(files)
        assert len(refs) == 15
        assert sel.is_grouped is True
        assert len(sel.groups) == 2
        pdf_group = next(g for g in sel.groups if g.format_name == "PDF")
        assert pdf_group.file_count == 12

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


class TestMukhaProgressAndRuntimeTruth:
    """Tests for 5-second progress promotion and runtime aggregation truth."""

    def test_five_second_rule_for_long_running_operations(self) -> None:
        workers = [
            WorkerPageView(worker_id="w-1", file_display_name="fast.pdf", stage="OCR", device_type="GPU", elapsed_ns=2_000_000_000),
            WorkerPageView(worker_id="w-2", file_display_name="slow.pdf", stage="Inference", device_type="CPU", elapsed_ns=8_000_000_000),
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

    @pytest.mark.parametrize(
        ("completed", "total", "expected_kind", "expected_pct"),
        [
            (5, 10, ProgressKind.KNOWN, 50.0),
            (0, 10, ProgressKind.KNOWN, 0.0),
            (10, 10, ProgressKind.KNOWN, 100.0),
            (3, 0, ProgressKind.KNOWN, 0.0),
        ],
    )
    def test_progress_states(self, completed: int, total: int, expected_kind: ProgressKind, expected_pct: float) -> None:
        prog = ProgressState.known(completed, total)
        assert prog.kind == expected_kind
        assert prog.percentage == expected_pct

        indet = ProgressState.indeterminate(completed=3)
        assert indet.kind == ProgressKind.INDETERMINATE

        unavail = ProgressState.unavailable()
        assert unavail.kind == ProgressKind.UNAVAILABLE

    def test_device_telemetry_aggregation_no_cpu_default(self) -> None:
        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp1",
                phase_name="ocr",
                component="yantra",
                duration_ns=500_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
                attributes={"device_type": "gpu"},
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
                confidence=ConfidenceValue(score=0.98, method="test", evidence={"test": True}),
            ),
        ]

        state = MukhaPresenter.build_monitor_view(
            run_id="run-102",
            status="running",
            started_at_ns=0,
            now_ns=1_000_000_000,
            files=(),
            maruti_records=maruti_recs,
            pramana_records=pramana_recs,
        )

        assert len(state.device_progress) == 1
        assert state.device_progress[0].device_type == "GPU"
        assert all(d.device_type != "CPU" for d in state.device_progress)

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
                phase_name="pipeline_stage",
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
                phase_name="retry_attempt",
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

    def test_inspector_view_aggregation(self) -> None:
        maruti_recs = [
            MarutiRecord(
                run_id="r1",
                request_id="req1",
                trace_id="tr1",
                span_id="sp1",
                phase_name="resolution",
                component="nabhi.manthan",
                duration_ns=250_000_000,
                timestamp_utc="2026-09-01T00:00:00Z",
                outcome="success",
            ),
        ]
        insp = MukhaPresenter.build_inspector_view(
            run_id="insp-1",
            status="SUCCESS",
            elapsed_ns=250_000_000,
            maruti_records=maruti_recs,
        )
        assert insp.run_id == "insp-1"
        assert len(insp.activity_logs) == 1
        assert len(insp.stage_timings) == 1
        assert insp.stage_timings[0].stage_name == "resolution"


class TestMukhaOwnershipAndTextualHeadlessApp:
    """Headless Textual UI flow and runtime boundary routing tests."""

    def test_app_launches_to_home_screen(self) -> None:
        async def _run() -> None:
            sel = InputSelectionView(total_files=3, total_size_bytes=3000, is_grouped=False)
            actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, available_actions=actions)

            app = MukhaApp(initial_state=init_state)

            async with app.run_test() as pilot:
                assert isinstance(app.screen, HomeScreen)
                assert app.screen.query_one("#home-req") is not None
                assert app.screen.query_one("#inputs-table") is not None

        asyncio.run(_run())

    def test_app_routes_start_intent_through_canonical_agni_owner(self, tmp_path: Path) -> None:
        async def _run() -> None:
            in_file = tmp_path / "sample.txt"
            in_file.write_text("hello", encoding="utf-8")
            req = Request(
                request_id="req-route-1",
                requirement="read_native",
                inputs=(
                    InputRef(
                        input_id="inp-1",
                        source_path=in_file,
                        display_name="sample.txt",
                        size_bytes=5,
                    ),
                ),
            )

            mock_agni = MagicMock()
            mock_agni.execute.return_value = Result(
                data="executed",
                artifacts=(),
            )

            sel = InputSelectionView(total_files=1, total_size_bytes=5, is_grouped=False)
            actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, available_actions=actions)

            app = MukhaApp(initial_state=init_state, agni=mock_agni, pending_request=req)

            async with app.run_test() as pilot:
                await pilot.click("#btn-start_run")
                await pilot.pause()

                mock_agni.execute.assert_called_once_with(req)
                assert isinstance(app.screen, SummaryScreen)

        asyncio.run(_run())

    def test_app_switch_to_monitor_and_summary(self) -> None:
        async def _run() -> None:
            sel = InputSelectionView(total_files=1, total_size_bytes=1000, is_grouped=False)
            mon_state = MukhaPresenter.build_monitor_view(
                run_id="run-tui-1",
                status="running",
                started_at_ns=0,
                now_ns=2_000_000_000,
                files=(),
            )
            sum_state = RunSummaryView(
                run_id="run-tui-1",
                status="SUCCESS",
                wall_time_ns=2_000_000_000,
                total_inputs=1,
                successful_files=1,
                warning_files=0,
                failed_files=0,
                quarantined_count=0,
                retry_count=0,
            )

            app_state = ApplicationViewState(
                current_screen="home",
                requirement="read_native",
                policy_label="Local only",
                input_selection=sel,
                active_run=mon_state,
                terminal_summary=sum_state,
            )

            app = MukhaApp(initial_state=app_state)

            async with app.run_test() as pilot:
                app.switch_to_monitor()
                await pilot.pause()
                assert isinstance(app.screen, MonitorScreen)

                app.switch_to_summary()
                await pilot.pause()
                assert isinstance(app.screen, SummaryScreen)

                app.switch_to_inspector()
                await pilot.pause()
                assert isinstance(app.screen, InspectorScreen)

                app.switch_to_home()
                await pilot.pause()
                assert isinstance(app.screen, HomeScreen)

        asyncio.run(_run())

    def test_small_terminal_size_does_not_crash(self) -> None:
        async def _run() -> None:
            sel = InputSelectionView(total_files=1, total_size_bytes=500, is_grouped=False)
            init_state = MukhaPresenter.build_home_view(input_selection=sel)

            app = MukhaApp(initial_state=init_state)

            async with app.run_test(size=(60, 15)) as pilot:
                assert isinstance(app.screen, HomeScreen)
                await pilot.pause()

        asyncio.run(_run())
