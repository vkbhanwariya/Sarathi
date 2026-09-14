"""Mukha - Console & Presentation for Sarathi.

Exposes:
- MukhaWebServer: Canonical Local Web presentation server for interactive document intelligence.
- NativePicker: Controlled native Windows file and folder picker.
- MukhaPresenter: Projects runtime facts and telemetry into typed view models.
- Presentation State: Typed immutable view models for Home, Monitor, Summary, and Inspector.
- Formatters: Pure functional formatters for durations, bytes, and confidence.
"""

from __future__ import annotations

from sarathi.mukha.intake import intake_from_paths
from sarathi.mukha.presenter import (
    MukhaPresenter,
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
from sarathi.mukha.state import (
    ActionParameterView,
    ActivityLogView,
    ApplicationViewState,
    ArtifactOutcomeView,
    AvailableActionView,
    DeviceProgressView,
    DeviceSummaryView,
    FallbackImprovementView,
    FileRunView,
    InputGroupView,
    InputItemView,
    InputSelectionView,
    InspectorViewState,
    OCRProfileEvidenceView,
    OperationView,
    PreflightView,
    ProgressKind,
    ProgressState,
    ReviewIntent,
    ReviewItemView,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    StartupViewState,
    WorkerPageView,
)
from sarathi.mukha.web import MukhaWebServer, NativePicker

__all__ = [
    "ActionParameterView",
    "ActivityLogView",
    "ApplicationViewState",
    "ArtifactOutcomeView",
    "AvailableActionView",
    "DeviceProgressView",
    "DeviceSummaryView",
    "FallbackImprovementView",
    "FileRunView",
    "InputGroupView",
    "InputItemView",
    "InputSelectionView",
    "InspectorViewState",
    "MukhaPresenter",
    "MukhaWebServer",
    "NativePicker",
    "OCRProfileEvidenceView",
    "OperationView",
    "PreflightView",
    "ProgressKind",
    "ProgressState",
    "ReviewIntent",
    "ReviewItemView",
    "RunSummaryView",
    "RunViewState",
    "StageTimingView",
    "StartupViewState",
    "WorkerPageView",
    "format_bytes",
    "format_confidence",
    "format_duration_ns",
    "intake_from_paths",
    "status_badge",
]
