"""Pramana — Confidence & Accuracy Telemetry for Darpana in Sarathi V2.

Defines:
- AccuracyValue: Evidence-backed quality measurement.
- PramanaRecord: Immutable quality observation capturing confidence and accuracy.

Preserves ExecutionContext identity, evidence lineage, and opaque subject references.
Never stores raw document text, file paths, or fabricated scores.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from sarathi.sankalpa import ConfidenceValue


@dataclass(frozen=True, slots=True)
class AccuracyValue:
    """Evidence-backed accuracy measurement."""

    score: float
    method: str
    evidence: Mapping[str, Any]

    def __post_init__(self) -> None:
        if isinstance(self.score, bool):
            raise TypeError("Accuracy score cannot be a boolean (True/False).")
        if not isinstance(self.score, (int, float)):
            raise TypeError(f"Accuracy score must be numeric, got {type(self.score).__name__}.")

        score_float = float(self.score)
        if math.isnan(score_float) or math.isinf(score_float):
            raise ValueError(f"Accuracy score cannot be NaN or Inf, got {score_float}.")
        if not (0.0 <= score_float <= 1.0):
            raise ValueError(f"Accuracy score must be a ratio in range [0.0, 1.0], got {score_float}.")
        object.__setattr__(self, "score", score_float)

        if not self.method or not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("Accuracy method must be a non-empty string describing the evaluation.")

        if not isinstance(self.evidence, Mapping):
            raise TypeError(f"evidence must be a Mapping, got {type(self.evidence).__name__}.")
        if len(self.evidence) == 0:
            raise ValueError("evidence must be a non-empty mapping containing factual verification details.")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))

    @property
    def as_ratio(self) -> float:
        """Return accuracy ratio [0.0, 1.0]."""
        return self.score

    @property
    def as_percent(self) -> float:
        """Return accuracy formatted as percentage [0.0, 100.0]."""
        return self.score * 100.0


@dataclass(frozen=True, slots=True)
class PramanaRecord:
    """Immutable quality observation record."""

    run_id: str
    request_id: str
    trace_id: str
    span_id: str
    capability_id: str
    stage: str
    timestamp_utc: str
    subject_id: str | None = None
    confidence: ConfidenceValue | None = None
    accuracy: AccuracyValue | None = None
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
        if not self.capability_id or not isinstance(self.capability_id, str) or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string.")
        if not self.stage or not isinstance(self.stage, str) or not self.stage.strip():
            raise ValueError("stage must be a non-empty string.")
        if not self.timestamp_utc or not isinstance(self.timestamp_utc, str):
            raise ValueError("timestamp_utc must be a non-empty string.")

        if self.subject_id is not None and not isinstance(self.subject_id, str):
            raise TypeError(f"subject_id must be a str or None, got {type(self.subject_id).__name__}.")

        if self.confidence is not None and not isinstance(self.confidence, ConfidenceValue):
            raise TypeError(f"confidence must be a ConfidenceValue or None, got {type(self.confidence).__name__}.")

        if self.accuracy is not None and not isinstance(self.accuracy, AccuracyValue):
            raise TypeError(f"accuracy must be an AccuracyValue or None, got {type(self.accuracy).__name__}.")

        if isinstance(self.attributes, Mapping):
            object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        else:
            raise TypeError(f"attributes must be a Mapping, got {type(self.attributes).__name__}.")
