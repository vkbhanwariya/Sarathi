"""Quarantine and Failure Lifecycle State for Nabhi Kernel in Sarathi V2.

Defines:
- QuarantineStatus: Lifecycle status for failed/quarantined attempts.
- LifecycleActionType: Supported lifecycle operations on quarantined items.
- LifecycleAction: Typed request to release, retry, or terminate quarantined items.
- RetryPolicy: Explicit bounded retry configuration.
- QuarantineRecord: Privacy-safe, hashed failure manifest.
- QuarantineStore: Atomic persistence for quarantine manifests under Runtime/Quarantine.

Maintains failure state only; contains no execution, hardware scheduling, caching, or security evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Sequence
import uuid

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import ExecutionContext, Request
from sarathi.sutra import Settings

if TYPE_CHECKING:
    from sarathi.nabhi.manthan import CapabilityPlan

_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class QuarantineStatus(str, Enum):
    """Lifecycle status for a quarantined pipeline item."""

    QUARANTINED = "quarantined"
    RETRIED = "retried"
    RELEASED = "released"
    TERMINAL = "terminal"


class LifecycleActionType(str, Enum):
    """Supported lifecycle actions for quarantined items."""

    RETRY = "retry"
    RELEASE = "release"
    TERMINATE = "terminate"


@dataclass(frozen=True, slots=True)
class LifecycleAction:
    """Typed request to perform a lifecycle transition on a quarantined item."""

    action: LifecycleActionType
    item_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)
    request: Request | None = None
    plan: CapabilityPlan | None = None
    context: ExecutionContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.action, LifecycleActionType):
            if isinstance(self.action, str):
                try:
                    object.__setattr__(self, "action", LifecycleActionType(self.action.lower()))
                except ValueError as err:
                    raise TypeError(f"Invalid lifecycle action type: {self.action!r}") from err
            else:
                raise TypeError(f"action must be a LifecycleActionType instance, got {type(self.action).__name__}.")

        if not isinstance(self.item_id, str) or not _SAFE_ID_PATTERN.match(self.item_id):
            raise ValueError(f"item_id must be a safe non-empty identifier, got {self.item_id!r}.")
        object.__setattr__(self, "item_id", self.item_id.strip())

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata).__name__}.")

        if self.request is not None and not isinstance(self.request, Request):
            raise TypeError(f"request must be a Request instance or None, got {type(self.request).__name__}.")

        if self.plan is not None:
            from sarathi.nabhi.manthan import CapabilityPlan as _PlanClass

            if not isinstance(self.plan, _PlanClass):
                raise TypeError(f"plan must be a CapabilityPlan instance or None, got {type(self.plan).__name__}.")

        if self.context is not None and not isinstance(self.context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(self.context).__name__}.")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Explicit bounded retry policy for pipeline execution."""

    max_retries: int = 0
    retryable_codes: tuple[FailureCode, ...] = (
        FailureCode.EXECUTION_FAILED,
        FailureCode.DEPENDENCY_UNAVAILABLE,
        FailureCode.RESOURCE_UNAVAILABLE,
    )

    def __post_init__(self) -> None:
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise TypeError(f"max_retries must be an integer, got {type(self.max_retries).__name__}.")
        if self.max_retries < 0:
            raise ValueError(f"max_retries cannot be negative, got {self.max_retries}.")

        if not isinstance(self.retryable_codes, (list, tuple, set)):
            raise TypeError(f"retryable_codes must be a sequence of FailureCode, got {type(self.retryable_codes).__name__}.")

        cleaned_codes: list[FailureCode] = []
        for i, code in enumerate(self.retryable_codes):
            if not isinstance(code, FailureCode):
                raise TypeError(f"retryable_codes[{i}] must be a FailureCode instance, got {type(code).__name__}.")
            cleaned_codes.append(code)
        object.__setattr__(self, "retryable_codes", tuple(cleaned_codes))

    def is_retryable(self, failure_code: FailureCode, current_attempt: int) -> bool:
        """Check whether a failure code is eligible for retry under the current attempt count."""
        if not isinstance(failure_code, FailureCode):
            return False
        return failure_code in self.retryable_codes and current_attempt < self.max_retries

    @classmethod
    def from_settings(cls, settings: Settings | None) -> RetryPolicy:
        """Derive a RetryPolicy from Sutra settings if present, or return zero retries."""
        if settings is None:
            return cls(max_retries=0)
        if not isinstance(settings, Settings):
            raise TypeError(f"settings must be a Settings instance or None, got {type(settings).__name__}.")

        pipeline_sec = settings.get_section("pipeline") or {}
        max_retries = pipeline_sec.get("max_retries", 0)
        return cls(max_retries=int(max_retries))


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Privacy-safe factual failure manifest stored in Runtime/Quarantine."""

    quarantine_id: str
    input_hash: str
    run_id: str
    request_id: str
    trace_id: str
    capability_id: str
    plugin_id: str
    failure_code: FailureCode
    profile: str
    attempt_count: int
    max_retries: int
    status: QuarantineStatus
    created_at_utc: str
    updated_at_utc: str
    provenance: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.quarantine_id, str) or not _SAFE_ID_PATTERN.match(self.quarantine_id):
            raise ValueError(f"quarantine_id must be a safe non-empty identifier, got {self.quarantine_id!r}.")
        if not isinstance(self.input_hash, str) or not self.input_hash.strip():
            raise ValueError("input_hash must be a non-empty string.")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id must be a non-empty string.")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string.")
        if not isinstance(self.trace_id, str) or not self.trace_id.strip():
            raise ValueError("trace_id must be a non-empty string.")
        if not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string.")
        if not isinstance(self.plugin_id, str) or not self.plugin_id.strip():
            raise ValueError("plugin_id must be a non-empty string.")
        if not isinstance(self.failure_code, FailureCode):
            raise TypeError(f"failure_code must be a FailureCode instance, got {type(self.failure_code).__name__}.")
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("profile must be a non-empty string.")
        if isinstance(self.attempt_count, bool) or not isinstance(self.attempt_count, int) or self.attempt_count < 0:
            raise ValueError(f"attempt_count must be a non-negative integer, got {self.attempt_count!r}.")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError(f"max_retries must be a non-negative integer, got {self.max_retries!r}.")
        if not isinstance(self.status, QuarantineStatus):
            raise TypeError(f"status must be a QuarantineStatus instance, got {type(self.status).__name__}.")
        if not isinstance(self.created_at_utc, str) or not self.created_at_utc.strip():
            raise ValueError("created_at_utc must be a non-empty ISO timestamp.")
        if not isinstance(self.updated_at_utc, str) or not self.updated_at_utc.strip():
            raise ValueError("updated_at_utc must be a non-empty ISO timestamp.")

        if isinstance(self.provenance, (list, tuple)):
            cleaned_prov: list[Mapping[str, Any]] = []
            for i, p in enumerate(self.provenance):
                if not isinstance(p, Mapping):
                    raise TypeError(f"provenance[{i}] must be a Mapping, got {type(p).__name__}.")
                cleaned_prov.append(MappingProxyType(dict(p)))
            object.__setattr__(self, "provenance", tuple(cleaned_prov))
        else:
            raise TypeError(f"provenance must be a sequence of Mapping, got {type(self.provenance).__name__}.")

    def to_dict(self) -> dict[str, Any]:
        """Convert record to a JSON-safe dictionary for manifest storage."""
        return {
            "quarantine_id": self.quarantine_id,
            "input_hash": self.input_hash,
            "run_id": self.run_id,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "capability_id": self.capability_id,
            "plugin_id": self.plugin_id,
            "failure_code": self.failure_code.value,
            "profile": self.profile,
            "attempt_count": self.attempt_count,
            "max_retries": self.max_retries,
            "status": self.status.value,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "provenance": [dict(p) for p in self.provenance],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> QuarantineRecord:
        """Construct record from manifest JSON dictionary."""
        return cls(
            quarantine_id=str(data["quarantine_id"]),
            input_hash=str(data["input_hash"]),
            run_id=str(data["run_id"]),
            request_id=str(data["request_id"]),
            trace_id=str(data["trace_id"]),
            capability_id=str(data["capability_id"]),
            plugin_id=str(data["plugin_id"]),
            failure_code=FailureCode(data["failure_code"]),
            profile=str(data["profile"]),
            attempt_count=int(data["attempt_count"]),
            max_retries=int(data["max_retries"]),
            status=QuarantineStatus(data["status"]),
            created_at_utc=str(data["created_at_utc"]),
            updated_at_utc=str(data["updated_at_utc"]),
            provenance=tuple(data.get("provenance", ())),
        )


class QuarantineStore:
    """Atomic file-backed persistence for quarantine manifests under Runtime/Quarantine."""

    def __init__(self, root: Path | str) -> None:
        """Initialize QuarantineStore at the specified root directory."""
        if isinstance(root, bool) or not isinstance(root, (str, Path)):
            raise TypeError(f"root must be a Path or str, got {type(root).__name__}.")
        raw_str = str(root).strip()
        if not raw_str:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="quarantine root cannot be an empty path.",
            )
        self._root: Path = Path(root).resolve()
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="Failed to create quarantine root directory.",
            ) from err

    @property
    def root(self) -> Path:
        """Return the resolved quarantine root path."""
        return self._root

    def quarantine(self, record: QuarantineRecord) -> Path:
        """Persist or overwrite a quarantine record atomically in Runtime/Quarantine/<quarantine_id>/manifest.json.

        Args:
            record: The QuarantineRecord to persist.

        Returns:
            Path to the written manifest.json.

        Raises:
            TypeError: If record is not a QuarantineRecord instance.
            DoshError(FailureCode.EXECUTION_FAILED): On write failure.
        """
        if not isinstance(record, QuarantineRecord):
            raise TypeError(f"record must be a QuarantineRecord instance, got {type(record).__name__}.")

        item_dir = self._root / record.quarantine_id
        try:
            item_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to create quarantine item directory.",
            ) from err

        manifest_path = item_dir / "manifest.json"
        manifest_bytes = json.dumps(record.to_dict(), indent=2, ensure_ascii=False).encode("utf-8")

        temp_path = item_dir / f".tmp_{uuid.uuid4().hex}_manifest.json"
        try:
            temp_path.write_bytes(manifest_bytes)
            temp_path.replace(manifest_path)
        except OSError as err:
            if temp_path.exists():
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to write quarantine manifest file.",
            ) from err

        return manifest_path

    def get_record(self, quarantine_id: str) -> QuarantineRecord | None:
        """Look up and load a quarantine record by ID, or return None if absent."""
        if not isinstance(quarantine_id, str):
            raise TypeError(f"quarantine_id must be a string, got {type(quarantine_id).__name__}.")
        cleaned_id = quarantine_id.strip()
        if not cleaned_id or not _SAFE_ID_PATTERN.match(cleaned_id):
            return None

        manifest_path = self._root / cleaned_id / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return QuarantineRecord.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError, OSError) as err:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Failed to read quarantine manifest record.",
            ) from err

    def update_status(
        self,
        quarantine_id: str,
        new_status: QuarantineStatus,
        *,
        attempt_count: int | None = None,
        updated_at_utc: str | None = None,
    ) -> QuarantineRecord:
        """Update the status of an existing quarantine record atomically.

        Args:
            quarantine_id: Target quarantine item ID.
            new_status: New status to transition to.
            attempt_count: Optional new attempt count.
            updated_at_utc: Optional ISO timestamp override.

        Returns:
            The updated QuarantineRecord.

        Raises:
            TypeError: On invalid input types.
            DoshError(FailureCode.VALIDATION_FAILED): If item does not exist or transition is invalid.
        """
        if not isinstance(new_status, QuarantineStatus):
            raise TypeError(f"new_status must be a QuarantineStatus instance, got {type(new_status).__name__}.")
        if not isinstance(quarantine_id, str):
            raise TypeError(f"quarantine_id must be a string, got {type(quarantine_id).__name__}.")
        cleaned_id = quarantine_id.strip()
        if not cleaned_id or not _SAFE_ID_PATTERN.match(cleaned_id):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Invalid quarantine item identifier format.",
            )

        existing = self.get_record(cleaned_id)
        if existing is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{cleaned_id}' does not exist.",
            )

        # Terminal state cannot be transitioned to any state (terminal is completed)
        if existing.status == QuarantineStatus.TERMINAL:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{cleaned_id}' is in terminal state and cannot transition to '{new_status.value}'.",
            )

        # Released state cannot be transitioned to any state (released is completed)
        if existing.status == QuarantineStatus.RELEASED:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{cleaned_id}' is in released state and cannot transition to '{new_status.value}'.",
            )

        from datetime import datetime, timezone

        ts_now = updated_at_utc or datetime.now(timezone.utc).isoformat()
        new_attempt = attempt_count if attempt_count is not None else existing.attempt_count

        updated_record = QuarantineRecord(
            quarantine_id=existing.quarantine_id,
            input_hash=existing.input_hash,
            run_id=existing.run_id,
            request_id=existing.request_id,
            trace_id=existing.trace_id,
            capability_id=existing.capability_id,
            plugin_id=existing.plugin_id,
            failure_code=existing.failure_code,
            profile=existing.profile,
            attempt_count=new_attempt,
            max_retries=existing.max_retries,
            status=new_status,
            created_at_utc=existing.created_at_utc,
            updated_at_utc=ts_now,
            provenance=existing.provenance,
        )

        self.quarantine(updated_record)
        return updated_record
