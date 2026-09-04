"""Maruti - Runtime, Logging & Performance Telemetry for Darpana in Sarathi V2.

Defines:
- MarutiRecord: Immutable structured runtime and performance event record.

Preserves ExecutionContext identity, monotonic duration, outcome, FailureCode, and safe attributes.
Does NOT configure Python logging handlers or write log files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from sarathi.dosh import FailureCode


@dataclass(frozen=True, slots=True)
class MarutiRecord:
    """Immutable runtime execution and performance measurement record."""

    run_id: str
    request_id: str
    trace_id: str
    span_id: str
    phase_name: str
    component: str
    timestamp_utc: str
    duration_ns: int
    outcome: str
    error_type: str | None = None
    failure_code: FailureCode | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not isinstance(self.run_id, str):
            raise ValueError("run_id must be a non-empty string.")
        if not self.request_id or not isinstance(self.request_id, str):
            raise ValueError("request_id must be a non-empty string.")
        if not self.trace_id or not isinstance(self.trace_id, str):
            raise ValueError("trace_id must be a non-empty string.")
        if not self.span_id or not isinstance(self.span_id, str):
            raise ValueError("span_id must be a non-empty string.")
        if not self.phase_name or not isinstance(self.phase_name, str) or not self.phase_name.strip():
            raise ValueError("phase_name must be a non-empty string.")
        if not self.component or not isinstance(self.component, str) or not self.component.strip():
            raise ValueError("component must be a non-empty string.")
        if not self.timestamp_utc or not isinstance(self.timestamp_utc, str):
            raise ValueError("timestamp_utc must be a non-empty string.")

        if not isinstance(self.duration_ns, int) or isinstance(self.duration_ns, bool):
            raise TypeError(f"duration_ns must be an integer, got {type(self.duration_ns).__name__}.")
        if self.duration_ns < 0:
            raise ValueError(f"duration_ns cannot be negative, got {self.duration_ns}.")

        if self.outcome not in ("success", "failure", "cancelled"):
            raise ValueError(f"outcome must be 'success', 'failure', or 'cancelled', got {self.outcome!r}.")

        if self.error_type is not None and not isinstance(self.error_type, str):
            raise TypeError(f"error_type must be a str or None, got {type(self.error_type).__name__}.")

        if self.failure_code is not None and not isinstance(self.failure_code, FailureCode):
            raise TypeError(f"failure_code must be a FailureCode or None, got {type(self.failure_code).__name__}.")

        if isinstance(self.attributes, Mapping):
            object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        else:
            raise TypeError(f"attributes must be a Mapping, got {type(self.attributes).__name__}.")
