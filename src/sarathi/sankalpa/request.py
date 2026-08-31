"""Request Contracts for Sarathi V2.

Defines the canonical processing request exchanged through the runtime.
Kept domain-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from sarathi.sankalpa.artifact import InputRef
from sarathi.sankalpa.execution_profile import ExecutionProfile


@dataclass(frozen=True, slots=True)
class Request:
    """Canonical domain-agnostic processing request."""

    request_id: str
    requirement: str
    inputs: tuple[InputRef, ...]
    profile: ExecutionProfile = ExecutionProfile.INSTANT
    custom_options: Mapping[str, Any] = field(default_factory=dict)
    output_root: Path | None = None
    preserve_partial: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.request_id or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string.")
        if not self.requirement or not self.requirement.strip():
            raise ValueError("requirement must be a non-empty string.")
        if isinstance(self.inputs, (list, tuple, set)):
            inputs_tuple = tuple(self.inputs)
            if not inputs_tuple:
                raise ValueError("inputs cannot be empty.")
            for i, inp in enumerate(inputs_tuple):
                if not isinstance(inp, InputRef):
                    raise TypeError(f"inputs[{i}] must be an InputRef instance, got {type(inp)}.")
            object.__setattr__(self, "inputs", inputs_tuple)
        else:
            raise TypeError(f"inputs must be a sequence of InputRef, got {type(self.inputs)}.")

        if not isinstance(self.profile, ExecutionProfile):
            object.__setattr__(self, "profile", ExecutionProfile.from_string(str(self.profile)))

        if self.output_root is not None and not isinstance(self.output_root, Path):
            object.__setattr__(self, "output_root", Path(self.output_root))

        if isinstance(self.custom_options, Mapping):
            object.__setattr__(self, "custom_options", MappingProxyType(dict(self.custom_options)))
        else:
            raise TypeError(f"custom_options must be a Mapping, got {type(self.custom_options)}.")

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")
