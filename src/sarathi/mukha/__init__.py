"""Mukha - Console & Presentation for Sarathi V2.

Exposes:
- MukhaApp: Canonical Textual application for interactive document intelligence.
- MukhaPresenter: Projects runtime facts and telemetry into typed view models.
- Presentation State: Typed immutable view models for Home, Monitor, Summary, and Inspector.
- Formatters: Pure functional formatters for durations, bytes, and confidence.
"""

from __future__ import annotations

from sarathi.mukha.app import (
    AarambhaScreen,
    HomeScreen,
    InspectorScreen,
    MonitorScreen,
    MukhaApp,
    ParikshaScreen,
    SummaryScreen,
)
from sarathi.mukha.components import (
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
from sarathi.mukha.intake import intake_from_paths
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    ArtifactOutcomeView,
    AvailableActionView,
    DeviceProgressView,
    DeviceSummaryView,
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
    ReviewItemView,
    RunSummaryView,
    RunViewState,
    StageTimingView,
    StartupViewState,
    WorkerPageView,
)

__all__ = [
    "AarambhaScreen",
    "ApplicationViewState",
    "ArtifactOutcomeView",
    "AvailableActionView",
    "DeviceProgressView",
    "DeviceSummaryView",
    "FileRunView",
    "HomeScreen",
    "InputGroupView",
    "InputItemView",
    "InputSelectionView",
    "InspectorScreen",
    "InspectorViewState",
    "intake_from_paths",
    "MonitorScreen",
    "MukhaApp",
    "MukhaPresenter",
    "OCRProfileEvidenceView",
    "OperationView",
    "ParikshaScreen",
    "PreflightView",
    "ProgressKind",
    "ProgressState",
    "ReviewItemView",
    "RunSummaryView",
    "RunViewState",
    "StageTimingView",
    "StartupViewState",
    "SummaryScreen",
    "WorkerPageView",
    "format_bytes",
    "format_confidence",
    "format_duration_ns",
    "status_badge",
]
