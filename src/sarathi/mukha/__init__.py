"""Mukha - Console & Presentation for Sarathi V2.

Exposes:
- Presenter: Projects runtime facts and telemetry into typed view models.
- Renderer: Renders presentation models into structured terminal views.
- Presentation State: Typed immutable view models for Home, Monitor, Summary, and Inspector.
"""

from __future__ import annotations

from sarathi.mukha.components import (
    format_bytes,
    format_confidence,
    format_duration_ns,
    format_table,
)
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.renderer import ConsoleRenderer
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
    "ConsoleRenderer",
    "DeviceProgressView",
    "DeviceSummaryView",
    "FileRunView",
    "InputGroupView",
    "InputItemView",
    "InputSelectionView",
    "InspectorViewState",
    "MukhaPresenter",
    "OCRProfileEvidenceView",
    "OperationView",
    "PreflightView",
    "ProgressKind",
    "ProgressState",
    "RunSummaryView",
    "RunViewState",
    "StageTimingView",
    "WorkerPageView",
    "format_bytes",
    "format_confidence",
    "format_duration_ns",
    "format_table",
]
