"""Result Contracts for Sarathi V2.

Defines:
- ConfidenceValue: Evidence-backed confidence measurement.
- ProvenanceRecord: Traceability record tying output to source document/stage/evidence.
- WarningRecord: Non-fatal operational warning.
- Result: Canonical result contract returned across capability boundaries.

Confidence Rules:
- Never default confidence to 1.0, 100%, or any fabricated value.
- Confidence is unavailable (None) by default unless calculated with evidence.
- Provenance records the exact method and evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from sarathi.sankalpa.artifact import ArtifactRef


@dataclass(frozen=True, slots=True)
class ConfidenceValue:
    """Evidence-backed confidence measurement."""

    score: float
    method: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if math.isnan(self.score) or math.isinf(self.score):
            raise ValueError(f"Confidence score cannot be NaN or Inf, got {self.score}.")
        if not (0.0 <= self.score <= 1.0 or 0.0 <= self.score <= 100.0):
            raise ValueError(f"Confidence score must be in range [0.0, 1.0] or [0, 100], got {self.score}.")
        if not self.method or not self.method.strip():
            raise ValueError("Confidence method must be a non-empty string describing the calculation.")
        if isinstance(self.evidence, Mapping):
            object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        else:
            raise TypeError(f"evidence must be a Mapping, got {type(self.evidence)}.")

    @property
    def as_ratio(self) -> float:
        """Return confidence normalized to [0.0, 1.0]."""
        return self.score / 100.0 if self.score > 1.0 else self.score

    @property
    def as_percent(self) -> float:
        """Return confidence normalized to [0.0, 100.0]."""
        return self.score if self.score > 1.0 else self.score * 100.0


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Lineage and source evidence for a processed output."""

    source_input_id: str | None = None
    source_file: str | None = None
    stage: str | None = None
    plugin_id: str | None = None
    capability_id: str | None = None
    page_number: int | None = None
    region: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    timestamp_utc: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.evidence, Mapping):
            object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))
        else:
            raise TypeError(f"evidence must be a Mapping, got {type(self.evidence)}.")


@dataclass(frozen=True, slots=True)
class WarningRecord:
    """Non-fatal operational warning record."""

    code: str
    message: str
    stage: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code or not self.code.strip():
            raise ValueError("Warning code must be a non-empty string.")
        if not self.message or not self.message.strip():
            raise ValueError("Warning message must be a non-empty string.")
        if isinstance(self.context, Mapping):
            object.__setattr__(self, "context", MappingProxyType(dict(self.context)))
        else:
            raise TypeError(f"context must be a Mapping, got {type(self.context)}.")


@dataclass(frozen=True, slots=True)
class Result:
    """Canonical result contract returned across capability boundaries."""

    data: Any = None
    artifacts: tuple[ArtifactRef, ...] = ()
    confidence: ConfidenceValue | None = None
    warnings: tuple[WarningRecord, ...] = ()
    provenance: tuple[ProvenanceRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.artifacts, (list, tuple)):
            for i, art in enumerate(self.artifacts):
                if not isinstance(art, ArtifactRef):
                    raise TypeError(f"artifacts[{i}] must be an ArtifactRef, got {type(art)}.")
            object.__setattr__(self, "artifacts", tuple(self.artifacts))
        else:
            raise TypeError(f"artifacts must be a sequence of ArtifactRef, got {type(self.artifacts)}.")

        if self.confidence is not None and not isinstance(self.confidence, ConfidenceValue):
            raise TypeError(f"confidence must be a ConfidenceValue instance or None, got {type(self.confidence)}.")

        if isinstance(self.warnings, (list, tuple)):
            for i, warn in enumerate(self.warnings):
                if not isinstance(warn, WarningRecord):
                    raise TypeError(f"warnings[{i}] must be a WarningRecord, got {type(warn)}.")
            object.__setattr__(self, "warnings", tuple(self.warnings))
        else:
            raise TypeError(f"warnings must be a sequence of WarningRecord, got {type(self.warnings)}.")

        if isinstance(self.provenance, (list, tuple)):
            for i, prov in enumerate(self.provenance):
                if not isinstance(prov, ProvenanceRecord):
                    raise TypeError(f"provenance[{i}] must be a ProvenanceRecord, got {type(prov)}.")
            object.__setattr__(self, "provenance", tuple(self.provenance))
        else:
            raise TypeError(f"provenance must be a sequence of ProvenanceRecord, got {type(self.provenance)}.")

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")
