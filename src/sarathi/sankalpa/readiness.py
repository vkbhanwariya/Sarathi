"""Capability Readiness Contracts for Sarathi V2.

Defines:
- ReadinessStatus: Enum representing capability readiness states.
- CapabilityReadiness: Immutable typed status of a capability's operational readiness.
- CapabilityReadinessProbe: Protocol for querying operational readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Mapping, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sarathi.dosh import FailureCode
    from sarathi.sankalpa.plugin import PluginServices


class ReadinessStatus(StrEnum):
    """Operational readiness state classifications."""

    READY = "ready"
    DISABLED = "disabled"
    INVALID_CONFIGURATION = "invalid_configuration"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class CapabilityReadiness:
    """Canonical typed operational readiness status for a capability."""

    ready: bool
    status: ReadinessStatus = ReadinessStatus.READY
    reason: str = ""
    failure_code: FailureCode | None = None


@runtime_checkable
class CapabilityReadinessProbe(Protocol):
    """Protocol for querying capability operational readiness."""

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        """Query readiness status for all capabilities provided by this probe."""
        ...
