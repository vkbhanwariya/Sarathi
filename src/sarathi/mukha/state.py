"""Typed Presentation State and Models for Mukha in Sarathi.

Defines immutable view state dataclasses for Home, Live Monitor, Run Summary,
and Inspector screens. Mukha consumes canonical state; it does not decide execution
or fabricate metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


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
    source_path: str | None = None


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
class ActionParameterView:
    """Declarative parameter descriptor for an available action/capability."""

    parameter_id: str
    display_name: str
    kind: str  # "select", "toggle", "text"
    default_value: Any = None
    options: tuple[tuple[str, str], ...] = ()
    is_required: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class AvailableActionView:
    """Action available to user on current screen."""

    action_id: str
    label: str
    is_enabled: bool = True
    disabled_reason: str | None = None
    description: str = ""
    parameters: tuple[ActionParameterView, ...] = ()


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
    idle_ns: int = 0
    status: str = "active"


@dataclass(frozen=True, slots=True)
class FileRunView:
    """Individual file execution progress within a run."""

    input_id: str
    display_name: str
    ordinal: int
    status: str
    elapsed_ns: int | None = None
    current_stage: str = ""
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
    progress: ProgressState | None = None


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

    artifact_id: str
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
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class WorkerPerformanceView:
    """Factual worker-level execution performance summary."""

    worker_id: str
    device_type: str
    device_id: str
    tasks_completed: int
    pages_completed: int
    total_duration_ms: float
    avg_duration_ms: float
    throughput_per_sec: float
    status: str = "IDLE"


@dataclass(frozen=True, slots=True)
class PageConfidenceView:
    """Factual page-level confidence metrics for inspection."""

    file_display_name: str
    page_number: int
    confidence_score: float | None = None
    region_count: int = 0
    min_confidence: float | None = None
    max_confidence: float | None = None
    review_recommended: bool = False


@dataclass(frozen=True, slots=True)
class RegionConfidenceView:
    """Factual region-level / block-level confidence details."""

    region_id: str
    file_display_name: str
    page_number: int
    confidence_score: float | None = None
    region_type: str = "text"
    method: str = "direct"
    review_recommended: bool = False
    original_confidence: float | None = None
    confidence_gain: float | None = None
    raw_confidence_score_delta: float | None = None
    fallback_engine: str | None = None


@dataclass(frozen=True, slots=True)
class FallbackImprovementView:
    """Factual telemetry of bounding-box quality delta by fallback engine (e.g. Tesseract 5)."""

    region_id: str
    file_display_name: str
    page_number: int
    original_confidence: float
    improved_confidence: float
    confidence_gain: float
    fallback_engine: str = "Tesseract 5"
    raw_confidence_score_delta: float | None = None


@dataclass(frozen=True, slots=True)
class ActivityLogView:
    """Typed structured activity log entry for inspector projection."""

    timestamp: str
    severity: str
    component: str
    message: str

    def __getitem__(self, index: int) -> str:
        """Support positional index access for backward compatibility with 4-tuple consumers."""
        return (self.timestamp, self.severity, self.component, self.message)[index]


@dataclass(frozen=True, slots=True)
class InspectorViewState:
    """Detailed inspection presentation state."""

    run_id: str
    status: str
    elapsed_ns: int
    activity_logs: tuple[ActivityLogView, ...] = ()
    stage_timings: tuple[StageTimingView, ...] = ()
    device_summaries: tuple[DeviceSummaryView, ...] = ()
    confidence_distribution: tuple[tuple[str, int], ...] = ()
    system_facts: tuple[tuple[str, str], ...] = ()
    worker_performance: tuple[WorkerPerformanceView, ...] = ()
    page_confidence: tuple[PageConfidenceView, ...] = ()
    region_confidence: tuple[RegionConfidenceView, ...] = ()
    fallback_improvements: tuple[FallbackImprovementView, ...] = ()


@dataclass(frozen=True, slots=True)
class StartupViewState:
    """Aarambha startup overlay presentation state."""

    is_initializing: bool = False
    current_stage: str = ""
    elapsed_ns: int = 0
    stages: tuple[tuple[str, str, int | None], ...] = ()
    is_failed: bool = False
    failure_message: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewItemView:
    """Typed review queue item presentation state for human exception inspection."""

    item_id: str
    attempt_id: str
    file_display_name: str
    stage: str
    source_text: str
    output_text: str
    issue_reason: str
    page_number: int | None = None
    confidence: float | None = None
    device_type: str = ""
    elapsed_ns: int = 0
    status: str = "pending"
    draft_proposal: str | None = None
    available_actions: tuple[str, ...] = ("accept", "unresolved")


@dataclass(frozen=True, slots=True)
class ReviewIntent:
    """Canonical human review intent submitted from Mukha presentation boundary."""

    item_id: str
    attempt_id: str
    action_id: str
    run_id: str | None = None
    proposed_value: str | None = None
    expected_revision: int | None = None


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
    review_queue: tuple[ReviewItemView, ...] = ()
    terminal_summary: RunSummaryView | None = None
    inspector: InspectorViewState | None = None
    startup: StartupViewState | None = None
    schema_version: int = 1
    state_revision: int = 0
