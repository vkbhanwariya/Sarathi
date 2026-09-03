"""Sankalpa — Canonical Contracts for Sarathi V2.

This package defines the small common data language used by the entire system:
- ExecutionProfile: INSTANT, ACCURATE, LAYOUT_PRESERVING, CUSTOM.
- InputRef, ArtifactIntent, ArtifactRef: Typed input sources and confirmed output artifacts.
- PluginInfo, SecurityDeclaration: Plugin metadata and declared security requirements.
- CapabilityDeclaration, DeviceType, DeviceRequirement: Capability definitions and resource requirements.
- Request: Domain-agnostic processing requests.
- ExecutionContext: Immutable request/trace correlation and runtime context.
- CanonicalDocument, PageData, TableData, TextSpan: Domain-agnostic document data representations.
- Result, ConfidenceValue, ProvenanceRecord, WarningRecord: Standard result contracts.
"""

from __future__ import annotations

from sarathi.sankalpa.artifact import ArtifactIntent, ArtifactPayload, ArtifactRef, InputRef
from sarathi.sankalpa.cancellation import CancellationToken
from sarathi.sankalpa.capability import (
    Capability,
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
)
from sarathi.sankalpa.context import ExecutionBinding, ExecutionContext
from sarathi.sankalpa.document import (
    CanonicalDocument,
    PageData,
    TableData,
    TextSpan,
)
from sarathi.sankalpa.execution_profile import (
    CustomProfileOptions,
    ExecutionProfile,
)
from sarathi.sankalpa.plugin import PluginInfo, SecurityDeclaration
from sarathi.sankalpa.request import Request
from sarathi.sankalpa.result import (
    ConfidenceValue,
    ProvenanceRecord,
    Result,
    WarningRecord,
)

__all__ = [
    "ArtifactIntent",
    "ArtifactPayload",
    "ArtifactRef",
    "CancellationToken",
    "CanonicalDocument",
    "Capability",
    "CapabilityDeclaration",
    "ConfidenceValue",
    "CustomProfileOptions",
    "DeviceRequirement",
    "DeviceType",
    "ExecutionBinding",
    "ExecutionContext",
    "ExecutionProfile",
    "InputRef",
    "PageData",
    "PluginInfo",
    "ProvenanceRecord",
    "Request",
    "Result",
    "SecurityDeclaration",
    "TableData",
    "TextSpan",
    "WarningRecord",
]
