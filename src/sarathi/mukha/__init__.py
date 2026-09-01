"""Mukha - Console & Presentation for Sarathi V2.

Exposes:
- MukhaApp: Canonical Textual application for interactive document intelligence.
- MukhaPresenter: Projects runtime facts and telemetry into typed view models.
- Presentation State: Typed immutable view models for Home, Monitor, Summary, and Inspector.
- Formatters: Pure functional formatters for durations, bytes, and confidence.
"""

from __future__ import annotations

from sarathi.mukha.app import (
    HomeScreen,
    InspectorScreen,
    MonitorScreen,
    MukhaApp,
    SummaryScreen,
)
from sarathi.mukha.components import (
    format_bytes,
    format_confidence,
    format_duration_ns,
    status_badge,
)
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
    RunSummaryView,
    RunViewState,
    StageTimingView,
    WorkerPageView,
)

__all__ = [
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
    "MonitorScreen",
    "MukhaApp",
    "MukhaPresenter",
    "OCRProfileEvidenceView",
    "OperationView",
    "PreflightView",
    "ProgressKind",
    "ProgressState",
    "RunSummaryView",
    "RunViewState",
    "StageTimingView",
    "SummaryScreen",
    "WorkerPageView",
    "format_bytes",
    "format_confidence",
    "format_duration_ns",
    "status_badge",
]
