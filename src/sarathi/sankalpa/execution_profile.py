"""Execution Profile Contracts for Sarathi V2.

Defines the canonical processing modes:
- Instant: Fastest viable path, minimum unnecessary fallback.
- Accurate: Accuracy priority, validation, targeted fallback/reprocessing.
- Layout Preserving: Accurate behavior preserving meaningful document layout/structure.
- Custom: Caller explicitly selects supported strategy/options.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class ExecutionProfile(StrEnum):
    """Canonical processing profiles defined across Sarathi V2."""

    INSTANT = "instant"
    ACCURATE = "accurate"
    LAYOUT_PRESERVING = "layout_preserving"
    CUSTOM = "custom"

    @classmethod
    def from_string(cls, value: str) -> ExecutionProfile:
        """Parse string to ExecutionProfile safely, case-insensitively."""
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(
            f"Invalid execution profile: {value!r}. "
            f"Allowed profiles: {[p.value for p in cls]}"
        )


@dataclass(frozen=True, slots=True)
class CustomProfileOptions:
    """Explicit parameters for Custom execution profile."""

    engine: str | None = None
    options: Mapping[str, Any] = field(default_factory=dict)
    fallback_enabled: bool = False
    validation_enabled: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.options, Mapping):
            object.__setattr__(self, "options", MappingProxyType(dict(self.options)))
        else:
            raise TypeError(f"options must be a Mapping, got {type(self.options)}.")
