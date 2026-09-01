"""Console Renderer for Mukha in Sarathi V2.

Renders typed presentation states into clean, structured terminal views.
"""

from __future__ import annotations

from sarathi.mukha.components import (
    format_bytes,
    format_confidence,
    format_duration_ns,
    format_table,
)
from sarathi.mukha.state import (
    ApplicationViewState,
    InspectorViewState,
    RunSummaryView,
    RunViewState,
)


class ConsoleRenderer:
    """Renders Mukha typed presentation state into clean terminal text."""

    @staticmethod
    def render_home(state: ApplicationViewState) -> str:
        """Render Screen 1: Griha - Home & Input Setup."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append(f"  SARATHI  |  Griha - Home  |  READY  |  Policy: {state.policy_label}")
        lines.append("=" * 72)
        lines.append(f"Requirement: {state.requirement}")
        lines.append("-" * 72)

        inp = state.input_selection
        lines.append(f"Inputs: {inp.total_files} files selected ({format_bytes(inp.total_size_bytes)})")

        if inp.is_grouped:
            group_rows = [
                (g.format_name, f"{g.file_count} files", format_bytes(g.total_size_bytes))
                for g in inp.groups
            ]
            lines.append(format_table(["Format", "Count", "Total Size"], group_rows))
        else:
            item_rows = [
                (item.input_id, item.display_name, format_bytes(item.size_bytes), "ELIGIBLE" if item.is_eligible else f"BLOCKED ({item.issue_reason})")
                for item in inp.items
            ]
            lines.append(format_table(["ID", "File Name", "Size", "Status"], item_rows))

        lines.append("-" * 72)
        if state.preflight:
            pf = state.preflight
            lines.append(f"Preflight: {pf.eligible_count} eligible | {pf.issue_count} issues")
            for fname, issue in pf.issues:
                lines.append(f"  ! {fname}: {issue}")

        lines.append("-" * 72)
        actions_str = "   ".join(f"[{a.label}]" if a.is_enabled else f"[{a.label} (disabled)]" for a in state.available_actions)
        lines.append(f"Actions: {actions_str}")
        lines.append("=" * 72)
        sep = chr(10)
        return sep.join(lines)

    @staticmethod
    def render_monitor(state: RunViewState) -> str:
        """Render Screen 2: Pravritti - Live Run Monitor."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append(f"  SARATHI  |  Pravritti - Live Monitor  |  {state.status.upper()}  |  Elapsed: {format_duration_ns(state.elapsed_ns)}")
        lines.append(f"Run ID: {state.run_id} | Files: {state.terminal_files}/{state.total_files} completed")
        lines.append("=" * 72)

        if state.current_focus:
            f = state.current_focus
            lines.append(f"Current: {f.operation_name} ({f.stage}) on {f.device_type} - {format_duration_ns(f.elapsed_ns)}")
            lines.append("-" * 72)

        if state.long_running:
            lines.append("Long-running Operations (>5s):")
            long_rows = [
                (op.operation_name, op.stage, op.device_type, format_duration_ns(op.elapsed_ns), op.last_activity or "-")
                for op in state.long_running
            ]
            lines.append(format_table(["Operation", "Stage", "Device", "Elapsed", "Activity"], long_rows))
            lines.append("-" * 72)

        if state.device_progress:
            lines.append("Device Progress:")
            dev_rows = [
                (
                    dp.device_type,
                    f"{dp.units_processed} units",
                    format_duration_ns(dp.avg_duration_ns) + "/unit" if dp.avg_duration_ns else "-",
                    format_confidence(dp.avg_confidence),
                )
                for dp in state.device_progress
            ]
            lines.append(format_table(["Device", "Units Processed", "Avg Time", "Avg Confidence"], dev_rows))
            lines.append("-" * 72)

        if state.files:
            lines.append("Files:")
            file_rows = [
                (f.display_name, f.current_stage, f.status.upper(), format_duration_ns(f.elapsed_ns))
                for f in state.files[:10]
            ]
            lines.append(format_table(["File", "Stage", "Status", "Elapsed"], file_rows))
            if len(state.files) > 10:
                lines.append(f"  ... and {len(state.files) - 10} more files (see Inspector)")

        lines.append("=" * 72)
        sep = chr(10)
        return sep.join(lines)

    @staticmethod
    def render_summary(state: RunSummaryView) -> str:
        """Render Screen 4: Samapti - Run Summary."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append(f"  SARATHI  |  Samapti - Run Summary  |  {state.status.upper()}  |  Run: {state.run_id}")
        lines.append(f"Wall Time: {format_duration_ns(state.wall_time_ns)} | Files: {state.successful_files} success, {state.warning_files} warning, {state.failed_files} failed")
        lines.append("=" * 72)

        lines.append(f"Outcome: {state.total_inputs} inputs, {state.retry_count} retries, {state.quarantined_count} quarantined")
        lines.append(f"Average Speed: {format_duration_ns(state.avg_page_time_ns)}/input | Average Confidence: {format_confidence(state.avg_confidence)}")
        acc_str = f"{state.accuracy * 100:.1f}%" if state.accuracy is not None else "unavailable (no reference corpus)"
        lines.append(f"Verified Accuracy: {acc_str}")
        lines.append("-" * 72)

        if state.device_summaries:
            lines.append("Device Execution Summary:")
            dev_rows = [
                (
                    ds.device_type,
                    str(ds.unit_count),
                    str(ds.attempts),
                    format_duration_ns(ds.avg_duration_ns),
                    format_duration_ns(ds.p95_duration_ns),
                    format_confidence(ds.avg_confidence),
                )
                for ds in state.device_summaries
            ]
            lines.append(format_table(["Device", "Units", "Attempts", "Avg/Unit", "p95/Unit", "Avg Conf"], dev_rows))
            lines.append("-" * 72)

        if state.stage_timings:
            lines.append("Stage Timing Breakdown:")
            stage_rows = [
                (st.stage_name, str(st.call_count), format_duration_ns(st.duration_ns))
                for st in state.stage_timings
            ]
            lines.append(format_table(["Stage", "Invocations", "Total Duration"], stage_rows))
            lines.append("-" * 72)

        if state.artifacts:
            lines.append("Confirmed Artifacts:")
            art_rows = [
                (art.artifact_type, art.display_name, format_bytes(art.size_bytes), art.sha256_hex[:12] + "...")
                for art in state.artifacts
            ]
            lines.append(format_table(["Type", "File Name", "Size", "SHA256"], art_rows))
            lines.append("-" * 72)

        if state.warnings:
            lines.append(f"Warnings ({len(state.warnings)}):")
            for w in state.warnings[:5]:
                lines.append(f"  ! {w}")
            lines.append("-" * 72)

        if state.failures:
            lines.append(f"Failures ({len(state.failures)}):")
            for f in state.failures[:5]:
                lines.append(f"  X {f}")
            lines.append("-" * 72)

        lines.append("Actions: [Inspect Run]   [New Run]")
        lines.append("=" * 72)
        sep = chr(10)
        return sep.join(lines)

    @staticmethod
    def render_inspector(state: InspectorViewState, tab: str = "performance") -> str:
        """Render Screen 5: Nirikshana - Run Inspector."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append(f"  SARATHI  |  Nirikshana - Run Inspector  |  {state.status.upper()}  |  Run: {state.run_id}")
        lines.append(f"Active Tab: [{tab.upper()}]  (Tabs: Activity | Performance | Quality | System)")
        lines.append("=" * 72)

        match tab.lower():
            case "activity":
                lines.append("Activity Log:")
                log_rows = [
                    (ts, level, comp, msg)
                    for ts, level, comp, msg in state.activity_logs[-20:]
                ]
                lines.append(format_table(["Timestamp", "Level", "Component", "Event"], log_rows))

            case "performance":
                lines.append("Performance Details:")
                if state.stage_timings:
                    stage_rows = [(st.stage_name, str(st.call_count), format_duration_ns(st.duration_ns)) for st in state.stage_timings]
                    lines.append(format_table(["Stage", "Calls", "Total Duration"], stage_rows))
                if state.device_summaries:
                    lines.append("\nDevice Metrics:")
                    dev_rows = [
                        (ds.device_type, str(ds.unit_count), format_duration_ns(ds.avg_duration_ns), format_duration_ns(ds.p95_duration_ns))
                        for ds in state.device_summaries
                    ]
                    lines.append(format_table(["Device", "Units", "Avg Duration", "p95 Duration"], dev_rows))

            case "quality":
                lines.append("Quality Distribution:")
                q_rows = [(bracket, str(count)) for bracket, count in state.confidence_distribution]
                lines.append(format_table(["Confidence Bracket", "Item Count"], q_rows))

            case "system":
                lines.append("System Facts:")
                lines.append(format_table(["Fact", "Value"], state.system_facts))

        lines.append("=" * 72)
        sep = chr(10)
        return sep.join(lines)
