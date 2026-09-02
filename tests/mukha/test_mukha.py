"""Comprehensive unit and headless Textual tests for Mukha - Console & Presentation Phase 1."""

import asyncio
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock
import pytest
from textual.widgets import Input

from sarathi.darpana import Darpana, MarutiRecord, PramanaRecord
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha, SecurityPolicy
from sarathi.mukha import (
    AarambhaScreen,
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
    ParikshaScreen,
    PreflightView,
    ProgressKind,
    ProgressState,
    ReviewItemView,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    StartupViewState,
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
    ExecutionContext,
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

        refs, sel, pf = MukhaPresenter.intake_from_paths(
            [valid_f1, valid_f2, missing_f, dir_f, valid_f1]
        )

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
        # Record observations across different runs
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

        from sarathi.mukha.app import _filter_run_telemetry

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


class TestMukhaTextualWorkerFlow:
    """Tests proving asynchronous worker execution, timer refreshes, and safe failure presentation."""

    def test_app_start_runs_off_event_loop_refreshes_and_transitions_to_summary(self, tmp_path: Path) -> None:
        async def _run() -> None:
            in_file = tmp_path / "sample.txt"
            in_file.write_text("hello", encoding="utf-8")
            req = Request(
                request_id="req-worker-1",
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

            real_darpana = Darpana(capacity=1000)
            exec_started = threading.Event()
            allow_finish = threading.Event()

            def mock_execute(request: Request, context: ExecutionContext | None = None) -> Result:
                assert context is not None
                real_darpana.record_maruti(
                    MarutiRecord(
                        run_id=context.run_id,
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        span_id=context.span_id,
                        phase_name="capability_execution",
                        component="yantra",
                        duration_ns=100_000_000,
                        timestamp_utc="2026-09-01T00:00:00Z",
                        outcome="success",
                        attributes={"device_type": "gpu"},
                    )
                )
                exec_started.set()
                allow_finish.wait(timeout=2.0)
                return Result(data="worker_success", artifacts=(), warnings=())

            mock_agni = MagicMock()
            mock_agni.execute.side_effect = mock_execute
            mock_agni.darpana = real_darpana

            sel = InputSelectionView(total_files=1, total_size_bytes=5, is_grouped=False)
            actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, available_actions=actions)

            app = MukhaApp(initial_state=init_state, agni=mock_agni, pending_request=req)

            async with app.run_test() as pilot:
                assert isinstance(app.screen, HomeScreen)

                await pilot.click("#btn-start_run")
                await pilot.pause()

                # Execution is running; MonitorScreen is active and timer is running
                assert isinstance(app.screen, MonitorScreen)
                assert app._monitor_timer is not None

                # Allow worker to complete
                allow_finish.set()
                await pilot.pause(0.15)

                # Transitions to SummaryScreen
                assert isinstance(app.screen, SummaryScreen)
                assert app.app_state.terminal_summary is not None
                assert app.app_state.terminal_summary.status == "SUCCESS"
                assert app.app_state.terminal_summary.successful_files is None
                assert app.app_state.terminal_summary.failed_files is None
                assert app.app_state.terminal_summary.quarantined_count is None
                assert app.app_state.terminal_summary.retry_count is None
                files_label = app.screen.query_one("#summary-files-count")
                assert "Files: - success, 0 warning, - failed" in str(files_label.render())

                # Timer is stopped upon completion
                assert app._monitor_timer is None

                # Correct ExecutionContext passed
                mock_agni.execute.assert_called_once()
                call_args = mock_agni.execute.call_args
                passed_context = call_args.kwargs.get("context")
                assert isinstance(passed_context, ExecutionContext)
                assert passed_context.run_id == app.app_state.terminal_summary.run_id

        asyncio.run(_run())

    def test_app_handles_dosh_failure_in_worker_gracefully(self, tmp_path: Path) -> None:
        async def _run() -> None:
            in_file = tmp_path / "fail.txt"
            in_file.write_text("bad", encoding="utf-8")
            req = Request(
                request_id="req-worker-fail",
                requirement="read_native",
                inputs=(
                    InputRef(
                        input_id="inp-1",
                        source_path=in_file,
                        display_name="fail.txt",
                        size_bytes=3,
                    ),
                ),
            )

            mock_agni = MagicMock()
            mock_agni.execute.side_effect = DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Resource limit exceeded",
            )
            mock_agni.darpana = Darpana(capacity=1000)

            sel = InputSelectionView(total_files=1, total_size_bytes=3, is_grouped=False)
            actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, available_actions=actions)

            app = MukhaApp(initial_state=init_state, agni=mock_agni, pending_request=req)

            async with app.run_test() as pilot:
                await pilot.click("#btn-start_run")
                await pilot.pause(0.1)

                assert isinstance(app.screen, SummaryScreen)
                assert app.app_state.terminal_summary is not None
                assert app.app_state.terminal_summary.status == "FAILED"
                assert app.app_state.terminal_summary.successful_files is None
                assert app.app_state.terminal_summary.warning_files is None
                assert app.app_state.terminal_summary.failed_files is None
                assert app.app_state.terminal_summary.quarantined_count is None
                assert app.app_state.terminal_summary.retry_count is None
                files_label = app.screen.query_one("#summary-files-count")
                assert "Files: - success, - warning, - failed" in str(files_label.render())
                assert len(app.app_state.terminal_summary.failures) == 1
                assert "[execution_failed] Resource limit exceeded" in app.app_state.terminal_summary.failures[0]
                assert app._monitor_timer is None

        asyncio.run(_run())

    def test_app_sanitizes_unexpected_exception_messages(self, tmp_path: Path) -> None:
        async def _run() -> None:
            in_file = tmp_path / "secret.txt"
            in_file.write_text("sensitive", encoding="utf-8")
            req = Request(
                request_id="req-worker-secret",
                requirement="read_native",
                inputs=(
                    InputRef(
                        input_id="inp-1",
                        source_path=in_file,
                        display_name="secret.txt",
                        size_bytes=9,
                    ),
                ),
            )

            # Unexpected exception with raw internal path / secret
            mock_agni = MagicMock()
            mock_agni.execute.side_effect = RuntimeError("SECRET_API_KEY_12345 in /internal/path/db.sqlite")
            mock_agni.darpana = Darpana(capacity=1000)

            sel = InputSelectionView(total_files=1, total_size_bytes=9, is_grouped=False)
            actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, available_actions=actions)

            app = MukhaApp(initial_state=init_state, agni=mock_agni, pending_request=req)

            async with app.run_test() as pilot:
                await pilot.click("#btn-start_run")
                await pilot.pause(0.1)

                assert isinstance(app.screen, SummaryScreen)
                assert app.app_state.terminal_summary is not None
                assert app.app_state.terminal_summary.status == "FAILED"
                assert len(app.app_state.terminal_summary.failures) == 1
                # Must NOT expose raw exception string or secrets
                assert "SECRET_API_KEY" not in app.app_state.terminal_summary.failures[0]
                assert "/internal/path" not in app.app_state.terminal_summary.failures[0]
                # Presents safe generic message + exception type only
                assert app.app_state.terminal_summary.failures[0] == "Internal execution error (RuntimeError)"

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


class TestMukhaParikshaAndReviewScreen:
    """Tests for Screen 3: Pariksha - Review & Exceptions."""

    def test_pariksha_empty_review_queue_renders_cleanly(self) -> None:
        async def _run() -> None:
            sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, review_queue=())

            app = MukhaApp(initial_state=init_state)

            async with app.run_test() as pilot:
                assert isinstance(app.screen, HomeScreen)
                # Press F3 or switch to review
                app.action_switch_review()
                await pilot.pause()

                assert isinstance(app.screen, ParikshaScreen)
                empty_lbl = app.screen.query_one("#review-empty-message")
                assert "No items currently pending review." in str(empty_lbl.render())

        asyncio.run(_run())

    def test_pariksha_renders_pending_review_items_losslessly(self) -> None:
        async def _run() -> None:
            item1 = ReviewItemView(
                item_id="rev-1",
                attempt_id="att-1",
                file_display_name="HDFC_Statement.pdf",
                stage="bank_extraction",
                source_text="कुल जमा 1,25,750.50",
                output_text="कुल जमा 1,25,150.50",
                issue_reason="Amount balance mismatch",
                page_number=17,
                confidence=0.712,
                device_type="CPU",
                elapsed_ns=6_140_000_000,
                available_actions=("accept", "validate_edit", "retry", "unresolved"),
            )

            sel = InputSelectionView(total_files=1, total_size_bytes=100, is_grouped=False)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, review_queue=(item1,))

            app = MukhaApp(initial_state=init_state)

            async with app.run_test() as pilot:
                app.action_switch_review()
                await pilot.pause()

                assert isinstance(app.screen, ParikshaScreen)
                hdr = app.screen.query_one("#review-header")
                assert "HDFC_Statement.pdf" in str(hdr.render())
                assert "Page 17" in str(hdr.render())

                src = app.screen.query_one("#review-source")
                assert "1,25,750.50" in str(src.render())

                out = app.screen.query_one("#review-output")
                assert "1,25,150.50" in str(out.render())

                metrics = app.screen.query_one("#review-metrics")
                assert "71.2%" in str(metrics.render())
                assert "Amount balance mismatch" in str(metrics.render())

                exec_lbl = app.screen.query_one("#review-execution")
                assert "CPU" in str(exec_lbl.render())
                assert "06.1s" in str(exec_lbl.render())

                # Check buttons rendered
                btn_accept = app.screen.query_one("#btn-review-accept")
                assert btn_accept is not None
                btn_retry = app.screen.query_one("#btn-review-retry")
                assert btn_retry is not None

        asyncio.run(_run())

    def test_review_view_model_immutability(self) -> None:
        item = ReviewItemView(
            item_id="rev-2",
            attempt_id="att-2",
            file_display_name="sample.pdf",
            stage="ocr",
            source_text="source",
            output_text="output",
            issue_reason="low_confidence",
            confidence=0.65,
        )
        assert item.available_actions == ("accept", "validate_edit", "retry", "unresolved")
        with pytest.raises(Exception):
            item.item_id = "mutated"  # type: ignore[misc]


class TestMukhaAarambhaStartupOverlay:
    """Tests for Screen 0: Aarambha - Startup Progress Overlay."""

    def test_startup_overlay_renders_when_threshold_exceeded(self) -> None:
        async def _run() -> None:
            startup_state = StartupViewState(
                is_initializing=True,
                current_stage="Detect execution devices",
                elapsed_ns=6_500_000_000,  # 6.5 seconds > 5.0s threshold
                stages=(
                    ("Configuration loaded", "completed", 120_000_000),
                    ("Darpana recording active", "completed", 40_000_000),
                    ("Discovering capabilities", "completed", 1_200_000_000),
                ),
            )
            sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, startup=startup_state)

            app = MukhaApp(initial_state=init_state)

            async with app.run_test() as pilot:
                # Must push AarambhaScreen on mount when initializing > 5s
                assert isinstance(app.screen, AarambhaScreen)
                hdr = app.screen.query_one("#aarambha-header")
                assert "Aarambha" in str(hdr.render())
                assert "06.5s" in str(hdr.render())

                # Dismiss transitions to HomeScreen
                await pilot.click("#btn-aarambha-dismiss")
                await pilot.pause()
                assert isinstance(app.screen, HomeScreen)

        asyncio.run(_run())

    def test_startup_overlay_skipped_when_under_five_seconds(self) -> None:
        async def _run() -> None:
            startup_state = StartupViewState(
                is_initializing=True,
                current_stage="Fast init",
                elapsed_ns=500_000_000,  # 0.5 seconds < 5.0s threshold
            )
            sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)
            init_state = MukhaPresenter.build_home_view(input_selection=sel, startup=startup_state)

            app = MukhaApp(initial_state=init_state)

            async with app.run_test() as pilot:
                # Fast startup must NOT flash AarambhaScreen; mounts directly to HomeScreen
                assert isinstance(app.screen, HomeScreen)
                await pilot.pause()

        asyncio.run(_run())


class TestMukhaInteractiveFlowAndCancellation:
    """Tests for interactive run execution, cancellation, and screen switching."""

    def test_interactive_cancel_run_transitions_to_cancelled_summary(self, tmp_path: Path) -> None:
        from sarathi.sankalpa import CancellationToken

        test_file = tmp_path / "test.txt"
        test_file.write_text("cancel test", encoding="utf-8")
        token = CancellationToken()

        req = Request(
            request_id="req-interactive-cancel",
            requirement="read_native",
            inputs=(InputRef("inp-1", test_file, "test.txt", 11),),
            cancellation_token=token,
        )

        mock_agni = MagicMock()

        def slow_execute(r: Request, context: ExecutionContext) -> Result:
            # Simulate cooperative cancellation during work
            for _ in range(50):
                time.sleep(0.01)
                if r.cancellation_token and r.cancellation_token.is_cancelled:
                    raise DoshError(code=FailureCode.CANCELLED, message="Operation cancelled")
            return Result(data="unreachable", artifacts=(), warnings=())

        mock_agni.execute.side_effect = slow_execute
        mock_agni.darpana = Darpana(capacity=1000)

        sel = InputSelectionView(total_files=1, total_size_bytes=11, is_grouped=False)
        actions = (AvailableActionView(action_id="start_run", label="Start Run"),)
        init_state = MukhaPresenter.build_home_view(input_selection=sel, available_actions=actions)

        app = MukhaApp(initial_state=init_state, agni=mock_agni, pending_request=req)

        async def _run() -> None:
            async with app.run_test() as pilot:
                # 1. Start run from Home
                await pilot.click("#btn-start_run")
                await pilot.pause(0.05)

                assert isinstance(app.screen, MonitorScreen)

                # 2. Click cancel button
                await pilot.click("#btn-cancel-run")
                await pilot.pause(0.1)

                # 3. Transitions cleanly to Summary with CANCELLED status
                assert isinstance(app.screen, SummaryScreen)
                assert app.app_state.terminal_summary is not None
                assert app.app_state.terminal_summary.status == "CANCELLED"
                assert "cancelled" in app.app_state.terminal_summary.failures[0].lower()

        asyncio.run(_run())

    def test_leaving_screens_preserves_application_state(self) -> None:
        sel = InputSelectionView(total_files=2, total_size_bytes=4096, is_grouped=False)
        init_state = MukhaPresenter.build_home_view(
            requirement="read_native",
            policy_label="Strict Policy",
            input_selection=sel,
        )

        app = MukhaApp(initial_state=init_state)

        async def _run() -> None:
            async with app.run_test() as pilot:
                assert isinstance(app.screen, HomeScreen)
                assert app.app_state.requirement == "read_native"
                assert app.app_state.input_selection.total_files == 2

                # Switch to Review
                app.action_switch_review()
                await pilot.pause()
                assert isinstance(app.screen, ParikshaScreen)

                # Switch back to Home; state is preserved
                app.action_switch_home()
                await pilot.pause()
                assert isinstance(app.screen, HomeScreen)
                assert app.app_state.requirement == "read_native"
                assert app.app_state.input_selection.total_files == 2

        asyncio.run(_run())

    def test_interactive_add_paths_and_switch_requirement(self, tmp_path: Path) -> None:
        doc1 = tmp_path / "doc1.txt"
        doc1.write_text("Document 1 content", encoding="utf-8")

        mock_agni = MagicMock()
        mock_agni.kavacha = Kavacha(
            policy=SecurityPolicy(
                allow_pii_access=False,
                allow_network_access=False,
                allow_external_processing=False,
                allowed_secrets=(),
            )
        )
        mock_agni.runtime_root = tmp_path / "Runtime"
        mock_agni.output_root = tmp_path / "Output"
        mock_agni.darpana = Darpana(capacity=1000)

        sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)
        init_state = MukhaPresenter.build_home_view(
            requirement="read_native",
            input_selection=sel,
        )

        app = MukhaApp(initial_state=init_state, agni=mock_agni)

        async def _run() -> None:
            async with app.run_test() as pilot:
                assert isinstance(app.screen, HomeScreen)
                assert app.app_state.input_selection.total_files == 0

                # 1. Add valid path interactively
                app.action_add_paths(str(doc1))
                await pilot.pause()

                assert app.app_state.input_selection.total_files == 1
                assert app._pending_request is not None
                assert len(app._pending_request.inputs) == 1

                # 2. Switch requirement
                app.action_select_requirement("bank_statements")
                await pilot.pause()

                assert app.app_state.requirement == "bank_statements"
                assert app._pending_request.requirement == "bank_statements"

                # 3. Open artifacts action does not crash
                app.action_open_artifacts()

        asyncio.run(_run())

    def test_audit_capability_status_truthfulness(self) -> None:
        statuses = MukhaPresenter.audit_capability_status()
        assert "read_native" in statuses
        assert statuses["read_native"][0] is True
        assert "bank_statements" in statuses
        assert statuses["bank_statements"][0] is True
        assert "font_conversion" in statuses
        assert "ocr" in statuses
        assert "translation" in statuses
