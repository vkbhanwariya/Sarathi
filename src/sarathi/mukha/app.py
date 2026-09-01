"""Textual Application and Screens for Mukha in Sarathi V2.

The canonical interactive presentation frontend for Sarathi.
Consumes typed presentation state and routes user intents to canonical runtime owners.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    TabbedContent,
    TabPane,
)

from sarathi.mukha.components import (
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
from sarathi.mukha.state import (
    ApplicationViewState,
    InspectorViewState,
    RunSummaryView,
    RunViewState,
)

if TYPE_CHECKING:
    from sarathi.agni import Agni
    from sarathi.sankalpa import Request, Result


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

            if self.state.current_focus:
                f = self.state.current_focus
                yield Label(f"Current Operation: {f.operation_name} ({f.stage}) on {f.device_type} - {format_duration_ns(f.elapsed_ns)}", id="monitor-focus")

            if self.state.long_running:
                yield Label("Long-running Operations (>5s):", id="long-running-title")
                lr_table = DataTable(id="long-running-table")
                lr_table.add_columns("Operation", "Stage", "Device", "Elapsed")
                for op in self.state.long_running:
                    lr_table.add_row(op.operation_name, op.stage, op.device_type, format_duration_ns(op.elapsed_ns))
                yield lr_table

            if self.state.device_progress:
                yield Label("Device Execution Progress:", id="device-progress-title")
                dev_table = DataTable(id="device-table")
                dev_table.add_columns("Device", "Executions", "Avg Duration", "Avg Confidence")
                for dp in self.state.device_progress:
                    avg_dur = format_duration_ns(dp.avg_duration_ns) + "/exec" if dp.avg_duration_ns else "-"
                    dev_table.add_row(dp.device_type, str(dp.execution_count), avg_dur, format_confidence(dp.avg_confidence))
                yield dev_table

            with Horizontal(id="monitor-actions"):
                yield Button("Cancel", id="btn-cancel-run", variant="error")
                yield Button("Summary", id="btn-goto-summary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-goto-summary":
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
            yield Label(f"Files: {self.state.successful_files} success, {self.state.warning_files} warning, {self.state.failed_files} failed", id="summary-files-count")
            yield Label(f"Outcome: {self.state.total_inputs} inputs, {self.state.retry_count} retries, {self.state.quarantined_count} quarantined", id="summary-outcome")

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

    def on_mount(self) -> None:
        self.push_screen(HomeScreen(self.app_state))

    def action_switch_home(self) -> None:
        self.switch_to_home()

    def action_switch_monitor(self) -> None:
        self.switch_to_monitor()

    def action_switch_summary(self) -> None:
        self.switch_to_summary()

    def action_switch_inspector(self) -> None:
        self.switch_to_inspector()

    def action_start_run(self) -> None:
        """Route start intent through Agni if available, transitioning to monitor/summary."""
        if self._agni is not None and self._pending_request is not None:
            # Route execution through canonical Agni composition root
            result = self._agni.execute(self._pending_request)
            from sarathi.mukha.presenter import MukhaPresenter
            summary_view = MukhaPresenter.build_summary_view(
                run_id=self._pending_request.request_id,
                status="SUCCESS",
                wall_time_ns=0,
                request=self._pending_request,
                result=result,
                successful_files=len(self._pending_request.inputs),
                warning_files=len(result.warnings),
                failed_files=0,
            )
            self.app_state = ApplicationViewState(
                current_screen="summary",
                requirement=self.app_state.requirement,
                policy_label=self.app_state.policy_label,
                input_selection=self.app_state.input_selection,
                preflight=self.app_state.preflight,
                available_actions=self.app_state.available_actions,
                terminal_summary=summary_view,
            )
            self.switch_to_summary()
        elif self.app_state.active_run is not None:
            self.switch_to_monitor()

    def switch_to_home(self) -> None:
        self.push_screen(HomeScreen(self.app_state))

    def switch_to_monitor(self) -> None:
        if self.app_state.active_run is not None:
            self.push_screen(MonitorScreen(self.app_state.active_run))

    def switch_to_summary(self) -> None:
        if self.app_state.terminal_summary is not None:
            self.push_screen(SummaryScreen(self.app_state.terminal_summary))

    def switch_to_inspector(self) -> None:
        if self.app_state.inspector is not None:
            self.push_screen(InspectorScreen(self.app_state.inspector))
        elif self.app_state.terminal_summary is not None:
            from sarathi.mukha.presenter import MukhaPresenter
            insp = MukhaPresenter.build_inspector_view(
                run_id=self.app_state.terminal_summary.run_id,
                status=self.app_state.terminal_summary.status,
                elapsed_ns=self.app_state.terminal_summary.wall_time_ns,
            )
            self.push_screen(InspectorScreen(insp))
