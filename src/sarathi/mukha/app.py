"""Textual Application and Screens for Mukha in Sarathi V2.

The canonical interactive presentation frontend for Sarathi.
Consumes typed presentation state and routes user intents to canonical runtime owners.
Runs runtime execution off the event loop via Textual worker threads.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
import uuid

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    TabbedContent,
    TabPane,
)

from sarathi.darpana import Darpana, MarutiRecord, PramanaRecord
from sarathi.dosh import DoshError
from sarathi.mukha.components import (
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    InspectorViewState,
    ReviewItemView,
    RunSummaryView,
    RunViewState,
    StartupViewState,
)
from sarathi.sankalpa import ExecutionContext

if TYPE_CHECKING:
    from sarathi.agni import Agni
    from sarathi.sankalpa import Request, Result


def _filter_run_telemetry(
    darpana: Darpana | None, run_id: str | None
) -> tuple[tuple[MarutiRecord, ...], tuple[PramanaRecord, ...]]:
    """Small private helper to filter parameterless Darpana snapshots by run_id."""
    if darpana is None or not run_id:
        return (), ()
    maruti = tuple(r for r in darpana.maruti_records() if r.run_id == run_id)
    pramana = tuple(r for r in darpana.pramana_records() if r.run_id == run_id)
    return maruti, pramana


class AarambhaScreen(Screen):
    """Screen 0 Overlay: Aarambha - Startup Progress."""

    def __init__(self, state: StartupViewState) -> None:
        super().__init__()
        self.state: StartupViewState = state

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="aarambha-container"):
            yield Label(f"Aarambha — Starting Sarathi ({format_duration_ns(self.state.elapsed_ns)})", id="aarambha-header")
            table = DataTable(id="aarambha-stages-table")
            table.add_columns("Stage", "Status", "Duration")
            for stage_name, st, dur_ns in self.state.stages:
                table.add_row(stage_name, st.upper(), format_duration_ns(dur_ns))
            yield table

            if self.state.current_stage:
                yield Label(f"Current: {self.state.current_stage}", id="aarambha-current-stage")

            if self.state.is_failed:
                yield Label(f"Startup Failed: {self.state.failure_message or 'Unknown error'}", id="aarambha-failure")
                with Horizontal(id="aarambha-actions"):
                    yield Button("Quit", id="btn-aarambha-quit")
            else:
                with Horizontal(id="aarambha-actions"):
                    yield Button("Dismiss", id="btn-aarambha-dismiss")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-aarambha-dismiss":
            self.app.switch_to_home()
        elif event.button.id == "btn-aarambha-quit":
            self.app.exit()


class HomeScreen(Screen):
    """Screen 1: Griha - Home & Input Setup."""

    def __init__(self, state: ApplicationViewState) -> None:
        super().__init__()
        self.state: ApplicationViewState = state

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="home-container"):
            yield Label(f"Requirement: {self.state.requirement}", id="home-req")
            yield Label(f"Policy: {self.state.policy_label}", id="home-policy")

            inp = self.state.input_selection
            yield Label(f"Inputs: {inp.total_files} files selected ({format_bytes(inp.total_size_bytes)})", id="home-inputs-title")

            table = DataTable(id="inputs-table")
            if inp.is_grouped:
                table.add_columns("Format", "Count", "Total Size")
                for g in inp.groups:
                    table.add_row(g.format_name, str(g.file_count), format_bytes(g.total_size_bytes))
            else:
                table.add_columns("ID", "File Name", "Size", "Status")
                for item in inp.items:
                    st = "ELIGIBLE" if item.is_eligible else f"BLOCKED ({item.issue_reason})"
                    table.add_row(item.input_id, item.display_name, format_bytes(item.size_bytes), st)
            yield table

            if self.state.preflight and self.state.preflight.issue_count > 0:
                pf = self.state.preflight
                yield Label(f"Preflight Issues ({pf.issue_count}):", id="preflight-title")
                for fname, issue in pf.issues:
                    yield Label(f"  ! {fname}: {issue}", classes="preflight-issue")

            with Horizontal(id="home-actions"):
                for action in self.state.available_actions:
                    btn = Button(action.label, id=f"btn-{action.action_id}", disabled=not action.is_enabled)
                    yield btn
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-start_run":
            self.app.action_start_run()


class MonitorScreen(Screen):
    """Screen 2: Pravritti - Live Run Monitor."""

    def __init__(self, state: RunViewState) -> None:
        super().__init__()
        self.state: RunViewState = state

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="monitor-container"):
            yield Label(f"Run ID: {self.state.run_id} | Status: {status_badge(self.state.status)} | Elapsed: {format_duration_ns(self.state.elapsed_ns)}", id="monitor-header")
            yield Label(f"Files Progress: {self.state.terminal_files}/{self.state.total_files} completed", id="monitor-files-progress")

            f_text = f"Current Operation: {self.state.current_focus.operation_name} ({self.state.current_focus.stage}) on {self.state.current_focus.device_type} - {format_duration_ns(self.state.current_focus.elapsed_ns)}" if self.state.current_focus else "Current Operation: -"
            yield Label(f_text, id="monitor-focus")

            yield Label("Long-running Operations (>5s):", id="long-running-title")
            lr_table = DataTable(id="long-running-table")
            lr_table.add_columns("Operation", "Stage", "Device", "Elapsed")
            for op in self.state.long_running:
                lr_table.add_row(op.operation_name, op.stage, op.device_type, format_duration_ns(op.elapsed_ns))
            yield lr_table

            yield Label("Device Execution Progress:", id="device-progress-title")
            dev_table = DataTable(id="device-table")
            dev_table.add_columns("Device", "Executions", "Avg Duration", "Avg Confidence")
            for dp in self.state.device_progress:
                avg_dur = format_duration_ns(dp.avg_duration_ns) + "/exec" if dp.avg_duration_ns else "-"
                dev_table.add_row(dp.device_type, str(dp.execution_count), avg_dur, format_confidence(dp.avg_confidence))
            yield dev_table

            with Horizontal(id="monitor-actions"):
                yield Button("Cancel", id="btn-cancel-run", disabled=False)
                yield Button("Summary", id="btn-goto-summary")
        yield Footer()

    def update_state(self, state: RunViewState) -> None:
        """Dynamically update monitor widgets on timer tick."""
        self.state = state
        try:
            hdr = self.query_one("#monitor-header", Label)
            hdr.update(f"Run ID: {self.state.run_id} | Status: {status_badge(self.state.status)} | Elapsed: {format_duration_ns(self.state.elapsed_ns)}")
            focus = self.query_one("#monitor-focus", Label)
            if self.state.current_focus:
                f = self.state.current_focus
                focus.update(f"Current Operation: {f.operation_name} ({f.stage}) on {f.device_type} - {format_duration_ns(f.elapsed_ns)}")
            else:
                focus.update("Current Operation: -")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-goto-summary":
            self.app.switch_to_summary()
        elif event.button.id == "btn-cancel-run":
            self.app.action_cancel_run()


def _fmt_count(val: int | None) -> str:
    return str(val) if val is not None else "-"


class ParikshaScreen(Screen):
    """Screen 3: Pariksha — Review & Exceptions."""

    def __init__(self, review_queue: tuple[ReviewItemView, ...]) -> None:
        super().__init__()
        self.review_queue: tuple[ReviewItemView, ...] = review_queue
        self.current_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="review-container"):
            if not self.review_queue:
                yield Label("Pariksha — Review & Exceptions (0 pending)", id="review-header")
                yield Label("No items currently pending review.", id="review-empty-message")
                with Horizontal(id="review-empty-actions"):
                    yield Button("Home", id="btn-review-home")
                    yield Button("Summary", id="btn-review-summary")
            else:
                total = len(self.review_queue)
                item = self.review_queue[min(self.current_idx, total - 1)]
                pg_str = f"Page {item.page_number} • " if item.page_number is not None else ""
                yield Label(
                    f"Review ─ {total} pending | Item {self.current_idx + 1}/{total} • {item.file_display_name} • {pg_str}{item.stage}",
                    id="review-header",
                )
                yield Label(f"Source : {item.source_text}", id="review-source")
                yield Label(f"Output : {item.output_text}", id="review-output")

                conf_str = format_confidence(item.confidence)
                yield Label(f"Confidence: {conf_str} • Validation: {item.issue_reason}", id="review-metrics")
                exec_dev = item.device_type or "-"
                yield Label(
                    f"Execution: {exec_dev} • Attempt {item.attempt_id} • {format_duration_ns(item.elapsed_ns)}",
                    id="review-execution",
                )

                with Horizontal(id="review-actions"):
                    for act in item.available_actions:
                        lbl = act.replace("_", " ").title()
                        yield Button(lbl, id=f"btn-review-{act}")

                with Horizontal(id="review-nav"):
                    yield Button("Previous", id="btn-review-prev", disabled=self.current_idx == 0)
                    yield Button("Next", id="btn-review-next", disabled=self.current_idx >= total - 1)
                    yield Button("Home", id="btn-review-home")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-review-home":
            self.app.switch_to_home()
        elif event.button.id == "btn-review-summary":
            self.app.switch_to_summary()


class SummaryScreen(Screen):
    """Screen 4: Samapti - Run Summary."""

    def __init__(self, state: RunSummaryView) -> None:
        super().__init__()
        self.state: RunSummaryView = state

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="summary-container"):
            yield Label(f"Run ID: {self.state.run_id} | Status: {status_badge(self.state.status)} | Wall Time: {format_duration_ns(self.state.wall_time_ns)}", id="summary-header")
            yield Label(f"Files: {_fmt_count(self.state.successful_files)} success, {_fmt_count(self.state.warning_files)} warning, {_fmt_count(self.state.failed_files)} failed", id="summary-files-count")
            yield Label(f"Outcome: {self.state.total_inputs} inputs, {_fmt_count(self.state.retry_count)} retries, {_fmt_count(self.state.quarantined_count)} quarantined", id="summary-outcome")

            acc_str = f"{self.state.accuracy * 100:.1f}%" if self.state.accuracy is not None else "-"
            yield Label(f"Average Speed: {format_duration_ns(self.state.avg_duration_per_input_ns)}/input | Average Confidence: {format_confidence(self.state.avg_confidence)} | Verified Accuracy: {acc_str}", id="summary-metrics")

            if self.state.artifacts:
                yield Label("Confirmed Output Artifacts:", id="artifacts-title")
                art_table = DataTable(id="artifacts-table")
                art_table.add_columns("Role", "File Name", "Size", "SHA256")
                for art in self.state.artifacts:
                    sha = art.sha256_hex[:12] + "..." if art.sha256_hex else "-"
                    art_table.add_row(art.role, art.display_name, format_bytes(art.size_bytes), sha)
                yield art_table

            if self.state.device_summaries:
                yield Label("Hardware Execution Summary:", id="hw-summary-title")
                hw_table = DataTable(id="hw-table")
                hw_table.add_columns("Device", "Executions", "Avg Duration", "p95 Duration", "Avg Confidence")
                for ds in self.state.device_summaries:
                    hw_table.add_row(
                        ds.device_type,
                        str(ds.execution_count),
                        format_duration_ns(ds.avg_duration_ns),
                        format_duration_ns(ds.p95_duration_ns),
                        format_confidence(ds.avg_confidence),
                    )
                yield hw_table

            if self.state.failures:
                yield Label(f"Failures ({len(self.state.failures)}):", id="failures-title")
                for f in self.state.failures:
                    yield Label(f"  X {f}", classes="failure-item")

            with Horizontal(id="summary-actions"):
                yield Button("Inspect Run", id="btn-inspect-run")
                yield Button("New Run", id="btn-new-run")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-inspect-run":
            self.app.switch_to_inspector()
        elif event.button.id == "btn-new-run":
            self.app.switch_to_home()


class InspectorScreen(Screen):
    """Screen 5: Nirikshana - Run Inspector."""

    def __init__(self, state: InspectorViewState) -> None:
        super().__init__()
        self.state: InspectorViewState = state

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="inspector-container"):
            yield Label(f"Run ID: {self.state.run_id} | Inspector", id="inspector-header")
            with TabbedContent(initial="tab-performance"):
                with TabPane("Activity", id="tab-activity"):
                    act_table = DataTable(id="activity-table")
                    act_table.add_columns("Timestamp", "Level", "Component", "Event")
                    for ts, lvl, comp, ev in self.state.activity_logs[-20:]:
                        act_table.add_row(ts, lvl, comp, ev)
                    yield act_table

                with TabPane("Performance", id="tab-performance"):
                    if self.state.stage_timings:
                        st_table = DataTable(id="stage-timings-table")
                        st_table.add_columns("Stage", "Invocations", "Total Duration")
                        for st in self.state.stage_timings:
                            st_table.add_row(st.stage_name, str(st.call_count), format_duration_ns(st.duration_ns))
                        yield st_table

                with TabPane("Quality", id="tab-quality"):
                    q_table = DataTable(id="quality-table")
                    q_table.add_columns("Confidence Bracket", "Item Count")
                    for b, c in self.state.confidence_distribution:
                        q_table.add_row(b, str(c))
                    yield q_table

                with TabPane("System", id="tab-system"):
                    sys_table = DataTable(id="system-table")
                    sys_table.add_columns("Fact", "Value")
                    for k, v in self.state.system_facts:
                        sys_table.add_row(k, v)
                    yield sys_table

            with Horizontal(id="inspector-actions"):
                yield Button("Back to Summary", id="btn-back-summary")
                yield Button("Home", id="btn-inspector-home")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-back-summary":
            self.app.switch_to_summary()
        elif event.button.id == "btn-inspector-home":
            self.app.switch_to_home()


class MukhaApp(App):
    """Canonical Textual application for Sarathi V2."""

    TITLE = "SARATHI"
    SUB_TITLE = "Local Document Intelligence System"

    BINDINGS = [
        ("f1", "switch_home", "Home"),
        ("f2", "switch_monitor", "Monitor"),
        ("f3", "switch_review", "Review"),
        ("f4", "switch_summary", "Summary"),
        ("f5", "switch_inspector", "Inspector"),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        initial_state: ApplicationViewState,
        agni: Agni | None = None,
        pending_request: Request | None = None,
    ) -> None:
        super().__init__()
        self.app_state: ApplicationViewState = initial_state
        self._agni: Agni | None = agni
        self._pending_request: Request | None = pending_request
        self._active_context: ExecutionContext | None = None
        self._active_run_id: str | None = None
        self._start_time_ns: int = 0
        self._monitor_timer: Timer | None = None

    def on_mount(self) -> None:
        if (
            self.app_state.startup is not None
            and self.app_state.startup.is_initializing
            and self.app_state.startup.elapsed_ns >= 5_000_000_000
        ):
            self.push_screen(AarambhaScreen(self.app_state.startup))
        else:
            self.push_screen(HomeScreen(self.app_state))

    def action_switch_home(self) -> None:
        self.switch_to_home()

    def action_switch_monitor(self) -> None:
        self.switch_to_monitor()

    def action_switch_review(self) -> None:
        self.switch_to_review()

    def action_switch_summary(self) -> None:
        self.switch_to_summary()

    def action_switch_inspector(self) -> None:
        self.switch_to_inspector()

    def action_cancel_run(self) -> None:
        """Request cooperative cancellation on the active request token."""
        if self._pending_request is not None and self._pending_request.cancellation_token is not None:
            self._pending_request.cancellation_token.cancel()
        elif self._active_context is not None and self._active_context.cancellation_token is not None:
            self._active_context.cancellation_token.cancel()

    def action_start_run(self) -> None:
        """Start execution asynchronously on a background worker thread and switch to Monitor."""
        if self._agni is not None and self._pending_request is not None:
            from dataclasses import replace
            from sarathi.sankalpa import CancellationToken

            cancel_token = self._pending_request.cancellation_token or CancellationToken()
            req = replace(self._pending_request, cancellation_token=cancel_token)
            self._pending_request = req

            # Create factual ExecutionContext with real identity
            run_id = f"run_{uuid.uuid4().hex[:12]}"
            trace_id = f"tr_{uuid.uuid4().hex[:16]}"
            span_id = f"sp_{uuid.uuid4().hex[:16]}"
            context = ExecutionContext(
                run_id=run_id,
                request_id=req.request_id,
                trace_id=trace_id,
                span_id=span_id,
                profile=req.profile,
                cancellation_token=cancel_token,
            )
            self._active_context = context
            self._active_run_id = run_id
            self._start_time_ns = time.perf_counter_ns()

            # Immediate transition to Monitor
            initial_mon = MukhaPresenter.build_monitor_view(
                run_id=run_id,
                status="running",
                started_at_ns=self._start_time_ns,
                now_ns=self._start_time_ns,
                files=(),
            )
            self.app_state = ApplicationViewState(
                current_screen="monitor",
                requirement=self.app_state.requirement,
                policy_label=self.app_state.policy_label,
                input_selection=self.app_state.input_selection,
                preflight=self.app_state.preflight,
                available_actions=(),
                active_run=initial_mon,
            )
            self.switch_to_monitor()

            # Start periodic Monitor refresh timer
            self._monitor_timer = self.set_interval(0.1, self._refresh_monitor_state)

            # Run execution off the Textual UI event loop in a worker thread
            self.run_worker(self._run_agni_worker, thread=True, exclusive=True)
        elif self.app_state.active_run is not None:
            self.switch_to_monitor()

    def _refresh_monitor_state(self) -> None:
        """Periodic timer tick refreshing monitor presentation state."""
        if self._active_run_id and self._start_time_ns > 0:
            now_ns = time.perf_counter_ns()
            darpana = getattr(self._agni, "darpana", None)
            maruti, pramana = _filter_run_telemetry(darpana, self._active_run_id)
            new_mon = MukhaPresenter.build_monitor_view(
                run_id=self._active_run_id,
                status="running",
                started_at_ns=self._start_time_ns,
                now_ns=now_ns,
                files=(),
                maruti_records=maruti,
                pramana_records=pramana,
                current_state=self.app_state.active_run,
            )
            self.app_state = ApplicationViewState(
                current_screen=self.app_state.current_screen,
                requirement=self.app_state.requirement,
                policy_label=self.app_state.policy_label,
                input_selection=self.app_state.input_selection,
                preflight=self.app_state.preflight,
                available_actions=self.app_state.available_actions,
                active_run=new_mon,
                terminal_summary=self.app_state.terminal_summary,
                inspector=self.app_state.inspector,
            )
            if isinstance(self.screen, MonitorScreen):
                self.screen.update_state(new_mon)

    def _stop_monitor_timer(self) -> None:
        if self._monitor_timer is not None:
            self._monitor_timer.pause()
            self._monitor_timer = None

    def _run_agni_worker(self) -> None:
        """Background thread execution of Agni runtime."""
        req = self._pending_request
        ctx = self._active_context
        start_ns = self._start_time_ns
        assert req is not None and ctx is not None and self._agni is not None

        try:
            result = self._agni.execute(req, context=ctx)
            elapsed = max(0, time.perf_counter_ns() - start_ns)
            self.call_from_thread(self._on_execution_success, req, ctx, result, elapsed)
        except Exception as exc:
            elapsed = max(0, time.perf_counter_ns() - start_ns)
            self.call_from_thread(self._on_execution_failure, req, ctx, exc, elapsed)

    def _on_execution_success(
        self,
        req: Request,
        ctx: ExecutionContext,
        result: Result,
        elapsed_ns: int,
    ) -> None:
        """Main thread callback for successful Agni execution."""
        self._stop_monitor_timer()

        darpana = getattr(self._agni, "darpana", None)
        maruti, pramana = _filter_run_telemetry(darpana, ctx.run_id)

        summary_view = MukhaPresenter.build_summary_view(
            run_id=ctx.run_id,
            status="SUCCESS",
            wall_time_ns=elapsed_ns,
            request=req,
            result=result,
            successful_files=None,
            warning_files=len(result.warnings),
            failed_files=None,
            quarantined_count=None,
            retry_count=None,
            maruti_records=maruti,
            pramana_records=pramana,
        )
        self.app_state = ApplicationViewState(
            current_screen="summary",
            requirement=self.app_state.requirement,
            policy_label=self.app_state.policy_label,
            input_selection=self.app_state.input_selection,
            preflight=self.app_state.preflight,
            available_actions=(),
            terminal_summary=summary_view,
        )
        self.switch_to_summary()

    def _on_execution_failure(
        self,
        req: Request,
        ctx: ExecutionContext,
        exc: Exception,
        elapsed_ns: int,
    ) -> None:
        """Main thread callback for failed or cancelled Agni execution with safe error messages."""
        self._stop_monitor_timer()

        is_cancelled = (
            (isinstance(exc, DoshError) and exc.context.get("cancelled") is True)
            or (req.cancellation_token is not None and req.cancellation_token.is_cancelled)
            or (ctx.cancellation_token is not None and ctx.cancellation_token.is_cancelled)
        )

        if is_cancelled:
            status = "CANCELLED"
            msg = "Execution cancelled by user"
        elif isinstance(exc, DoshError):
            status = "FAILED"
            msg = f"[{exc.code.value}] {exc.message}"
        else:
            status = "FAILED"
            msg = f"Internal execution error ({type(exc).__name__})"

        darpana = getattr(self._agni, "darpana", None)
        maruti, pramana = _filter_run_telemetry(darpana, ctx.run_id)

        from sarathi.sankalpa import Result as SankalpaResult

        empty_res = SankalpaResult(data="", artifacts=(), warnings=())
        summary_view = MukhaPresenter.build_summary_view(
            run_id=ctx.run_id,
            status=status,
            wall_time_ns=elapsed_ns,
            request=req,
            result=empty_res,
            successful_files=None,
            warning_files=None,
            failed_files=None,
            quarantined_count=None,
            retry_count=None,
            failures=(msg,),
            maruti_records=maruti,
            pramana_records=pramana,
        )
        self.app_state = ApplicationViewState(
            current_screen="summary",
            requirement=self.app_state.requirement,
            policy_label=self.app_state.policy_label,
            input_selection=self.app_state.input_selection,
            preflight=self.app_state.preflight,
            available_actions=(),
            terminal_summary=summary_view,
        )
        self.switch_to_summary()

    def switch_to_home(self) -> None:
        self.push_screen(HomeScreen(self.app_state))

    def switch_to_monitor(self) -> None:
        if self.app_state.active_run is not None:
            self.push_screen(MonitorScreen(self.app_state.active_run))

    def switch_to_review(self) -> None:
        self.push_screen(ParikshaScreen(self.app_state.review_queue))

    def switch_to_aarambha(self, startup: StartupViewState | None = None) -> None:
        st = startup or self.app_state.startup or StartupViewState()
        self.push_screen(AarambhaScreen(st))

    def switch_to_summary(self) -> None:
        if self.app_state.terminal_summary is not None:
            self.push_screen(SummaryScreen(self.app_state.terminal_summary))

    def switch_to_inspector(self) -> None:
        if self.app_state.inspector is not None:
            self.push_screen(InspectorScreen(self.app_state.inspector))
        elif self.app_state.terminal_summary is not None:
            darpana = getattr(self._agni, "darpana", None)
            maruti, pramana = _filter_run_telemetry(darpana, self.app_state.terminal_summary.run_id)
            insp = MukhaPresenter.build_inspector_view(
                run_id=self.app_state.terminal_summary.run_id,
                status=self.app_state.terminal_summary.status,
                elapsed_ns=self.app_state.terminal_summary.wall_time_ns,
                maruti_records=maruti,
                pramana_records=pramana,
            )
            self.push_screen(InspectorScreen(insp))
