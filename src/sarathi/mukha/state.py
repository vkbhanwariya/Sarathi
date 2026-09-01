"""Typed Presentation State and Models for Mukha in Sarathi V2.

Defines immutable view state dataclasses for Home, Live Monitor, Run Summary,
and Inspector screens. Mukha consumes canonical state; it does not decide execution
or fabricate metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class ProgressKind(StrEnum):
    """Progress measurement classification."""

    KNOWN = "known"
    INDETERMINATE = "indeterminate"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ProgressState:
    """Factual progress representation."""

    kind: ProgressKind
    completed: int = 0
    total: int = 0
    percentage: float | None = None

    @classmethod
    def known(cls, completed: int, total: int) -> ProgressState:
        if total <= 0:
            raise ValueError(f"total must be greater than 0 for KNOWN progress, got {total}.")
        if completed < 0:
            raise ValueError(f"completed cannot be negative, got {completed}.")
        if completed > total:
            raise ValueError(f"completed ({completed}) cannot exceed total ({total}).")
        pct = min(100.0, max(0.0, (completed / total) * 100.0))
        return cls(kind=ProgressKind.KNOWN, completed=completed, total=total, percentage=pct)

    @classmethod
    def indeterminate(cls, completed: int = 0) -> ProgressState:
        return cls(kind=ProgressKind.INDETERMINATE, completed=completed)

    @classmethod
    def unavailable(cls) -> ProgressState:
        return cls(kind=ProgressKind.UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class InputGroupView:
    """Grouped view of multiple input files by detected/declared format."""

    format_name: str
    file_count: int
    total_size_bytes: int


@dataclass(frozen=True, slots=True)
class InputItemView:
    """Single input document presentation view."""

    input_id: str
    display_name: str
    size_bytes: int
    media_type: str | None = None
    is_eligible: bool = True
    issue_reason: str | None = None


@dataclass(frozen=True, slots=True)
class InputSelectionView:
    """Inputs selection presentation state."""

    total_files: int
    total_size_bytes: int
    is_grouped: bool
    groups: tuple[InputGroupView, ...] = ()
    items: tuple[InputItemView, ...] = ()


@dataclass(frozen=True, slots=True)
class PreflightView:
    """Input preflight validation presentation view."""

    eligible_count: int
    issue_count: int
    issues: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class OCRProfileEvidenceView:
    """Factual evidence view for an execution profile."""

    profile: str
    sample_count: int
    average_duration_ns: int | None = None
    average_confidence: float | None = None
    verified_accuracy: float | None = None


@dataclass(frozen=True, slots=True)
class AvailableActionView:
    """Action available to user on current screen."""

    action_id: str
    label: str
    is_enabled: bool = True
    disabled_reason: str | None = None


@dataclass(frozen=True, slots=True)
class OperationView:
    """Active operation presentation state."""

    operation_name: str
    stage: str
    device_type: str
    elapsed_ns: int
    is_long_running: bool
    last_activity: str | None = None
    progress: ProgressState | None = None


@dataclass(frozen=True, slots=True)
class WorkerPageView:
    """Active worker or page execution presentation state."""

    worker_id: str
    file_display_name: str
    page_number: int | None = None
    stage: str = ""
    device_type: str = ""
    elapsed_ns: int = 0
    status: str = "active"


@dataclass(frozen=True, slots=True)
class FileRunView:
    """Individual file execution progress within a run."""

    input_id: str
    display_name: str
    ordinal: int
    status: str
    elapsed_ns: int
    current_stage: str
    warning_count: int = 0
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceProgressView:
    """Factual device throughput and quality breakdown."""

    device_type: str
    execution_count: int
    total_duration_ns: int
    avg_duration_ns: int | None
    avg_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class RunViewState:
    """Live monitor presentation state for an active run."""

    run_id: str
    status: str
    elapsed_ns: int
    terminal_files: int
    total_files: int
    current_focus: OperationView | None = None
    files: tuple[FileRunView, ...] = ()
    active_workers: tuple[WorkerPageView, ...] = ()
    device_progress: tuple[DeviceProgressView, ...] = ()
    long_running: tuple[OperationView, ...] = ()


@dataclass(frozen=True, slots=True)
class StageTimingView:
    """Factual timing measured for a pipeline stage."""

    stage_name: str
    duration_ns: int
    call_count: int


@dataclass(frozen=True, slots=True)
class DeviceSummaryView:
    """Factual hardware execution summary for completed run."""

    device_type: str
    execution_count: int
    attempts: int
    avg_duration_ns: int | None
    p95_duration_ns: int | None
    avg_confidence: float | None


@dataclass(frozen=True, slots=True)
class ArtifactOutcomeView:
    """Confirmed generated artifact presentation view."""

    role: str
    display_name: str
    size_bytes: int | None = None
    sha256_hex: str | None = None


@dataclass(frozen=True, slots=True)
class RunSummaryView:
    """Terminal run summary presentation state."""

    run_id: str
    status: str
    wall_time_ns: int
    total_inputs: int
    successful_files: int | None = None
    warning_files: int | None = None
    failed_files: int | None = None
    quarantined_count: int | None = None
    retry_count: int | None = None
    avg_duration_per_input_ns: int | None = None
    avg_confidence: float | None = None
    accuracy: float | None = None
    stage_timings: tuple[StageTimingView, ...] = ()
    device_summaries: tuple[DeviceSummaryView, ...] = ()
    artifacts: tuple[ArtifactOutcomeView, ...] = ()
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InspectorViewState:
    """Detailed inspection presentation state."""

    run_id: str
    status: str
    elapsed_ns: int
    activity_logs: tuple[tuple[str, str, str, str], ...] = ()
    stage_timings: tuple[StageTimingView, ...] = ()
    device_summaries: tuple[DeviceSummaryView, ...] = ()
    confidence_distribution: tuple[tuple[str, int], ...] = ()
    system_facts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ApplicationViewState:
    """Top-level consolidated Mukha application presentation state."""

    current_screen: str
    requirement: str
    policy_label: str
    input_selection: InputSelectionView
    preflight: PreflightView | None = None
    available_actions: tuple[AvailableActionView, ...] = ()
    active_run: RunViewState | None = None
    terminal_summary: RunSummaryView | None = None
    inspector: InspectorViewState | None = None
