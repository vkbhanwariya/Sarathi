"""Context Contracts for Sarathi V2.

Defines:
- ExecutionContext: Immutable request/trace identity and controlled runtime context.

Must NOT become a global mutable state container or service locator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.sankalpa.execution_profile import ExecutionProfile

if TYPE_CHECKING:
    from sarathi.sankalpa.cancellation import CancellationToken


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Immutable execution context passed across capability boundaries."""

    run_id: str
    request_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    profile: ExecutionProfile = ExecutionProfile.INSTANT
    quarantine_attempt: int = 0
    is_retry: bool = False
    cancellation_token: CancellationToken | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id or not self.run_id.strip():
            raise ValueError("run_id must be a non-empty string.")
        if not self.request_id or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string.")
        if not self.trace_id or not self.trace_id.strip():
            raise ValueError("trace_id must be a non-empty string.")
        if not self.span_id or not self.span_id.strip():
            raise ValueError("span_id must be a non-empty string.")
        if self.quarantine_attempt < 0:
            raise ValueError(f"quarantine_attempt cannot be negative (got {self.quarantine_attempt}).")
        if not isinstance(self.profile, ExecutionProfile):
            object.__setattr__(self, "profile", ExecutionProfile.from_string(str(self.profile)))
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")

        if self.cancellation_token is not None:
            from sarathi.sankalpa.cancellation import CancellationToken

            if not isinstance(self.cancellation_token, CancellationToken):
                raise TypeError(
                    f"cancellation_token must be a CancellationToken instance or None, "
                    f"got {type(self.cancellation_token).__name__}."
                )

    def child_span(self, span_id: str, extra_metadata: Mapping[str, Any] | None = None) -> ExecutionContext:
        """Create a child execution context with this context as parent."""
        if not span_id or not span_id.strip():
            raise ValueError("span_id must be a non-empty string.")
        merged_meta = dict(self.metadata)
        if extra_metadata:
            merged_meta.update(extra_metadata)
        return ExecutionContext(
            run_id=self.run_id,
            request_id=self.request_id,
            trace_id=self.trace_id,
            span_id=span_id,
            parent_span_id=self.span_id,
            profile=self.profile,
            quarantine_attempt=self.quarantine_attempt,
            is_retry=self.is_retry,
            cancellation_token=self.cancellation_token,
            metadata=merged_meta,
        )

    def with_retry(self, quarantine_attempt: int) -> ExecutionContext:
        """Create a context copy for retry execution."""
        return ExecutionContext(
            run_id=self.run_id,
            request_id=self.request_id,
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            profile=self.profile,
            quarantine_attempt=quarantine_attempt,
            is_retry=True,
            cancellation_token=self.cancellation_token,
            metadata=dict(self.metadata),
        )
