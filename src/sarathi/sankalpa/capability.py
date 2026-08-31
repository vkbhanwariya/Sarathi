"""Capability Contracts for Sarathi V2.

Defines:
- DeviceType: CPU, GPU, NPU.
- DeviceRequirement: Execution and device preferences declared by capabilities.
- CapabilityDeclaration: Canonical capability declaration contract.

Capabilities declare requirements only; Yantra allocates hardware and executes work.
Contains no scheduling, resource allocation, device selection, or execution logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from sarathi.sankalpa.execution_profile import ExecutionProfile


class DeviceType(StrEnum):
    """Execution hardware device classes."""

    CPU = "cpu"
    GPU = "gpu"
    NPU = "npu"

    @classmethod
    def from_string(cls, value: str) -> DeviceType:
        """Parse string to DeviceType safely."""
        normalized = value.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValueError(
            f"Invalid device type: {value!r}. Allowed devices: {[d.value for d in cls]}"
        )


@dataclass(frozen=True, slots=True)
class DeviceRequirement:
    """Declared execution hardware requirements."""

    preferred_devices: tuple[DeviceType, ...] = (DeviceType.CPU,)
    supported_devices: tuple[DeviceType, ...] = (DeviceType.CPU,)
    parallelizable: bool = True
    estimated_memory_bytes: int | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.preferred_devices, (list, tuple, set)):
            preferred = tuple(
                d if isinstance(d, DeviceType) else DeviceType.from_string(str(d))
                for d in self.preferred_devices
            )
            object.__setattr__(self, "preferred_devices", preferred)
        else:
            raise TypeError(f"preferred_devices must be a sequence of DeviceType, got {type(self.preferred_devices)}.")

        if isinstance(self.supported_devices, (list, tuple, set)):
            supported = tuple(
                d if isinstance(d, DeviceType) else DeviceType.from_string(str(d))
                for d in self.supported_devices
            )
            object.__setattr__(self, "supported_devices", supported)
        else:
            raise TypeError(f"supported_devices must be a sequence of DeviceType, got {type(self.supported_devices)}.")

        if self.estimated_memory_bytes is not None and self.estimated_memory_bytes < 0:
            raise ValueError(
                f"estimated_memory_bytes cannot be negative (got {self.estimated_memory_bytes})."
            )


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """Canonical capability declaration registered with Nabhi."""

    capability_id: str
    plugin_id: str
    version: str
    description: str = ""
    supported_profiles: tuple[ExecutionProfile, ...] = (
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    )
    device_requirement: DeviceRequirement = field(default_factory=DeviceRequirement)
    supported_input_types: tuple[str, ...] = ()
    produces_artifacts: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability_id or not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string.")
        if not self.plugin_id or not self.plugin_id.strip():
            raise ValueError("plugin_id must be a non-empty string.")
        if not self.version or not self.version.strip():
            raise ValueError("version must be a non-empty string.")
        if not isinstance(self.device_requirement, DeviceRequirement):
            raise TypeError(f"device_requirement must be a DeviceRequirement, got {type(self.device_requirement)}.")
        if isinstance(self.supported_profiles, (list, tuple, set)):
            profiles = tuple(
                p if isinstance(p, ExecutionProfile) else ExecutionProfile.from_string(str(p))
                for p in self.supported_profiles
            )
            if not profiles:
                raise ValueError("supported_profiles cannot be empty.")
            object.__setattr__(self, "supported_profiles", profiles)
        else:
            raise TypeError(f"supported_profiles must be a sequence of ExecutionProfile, got {type(self.supported_profiles)}.")

        if isinstance(self.supported_input_types, (list, tuple, set)):
            cleaned_inputs = tuple(
                t.strip().lower() for t in self.supported_input_types if t and t.strip()
            )
            object.__setattr__(self, "supported_input_types", cleaned_inputs)
        else:
            raise TypeError(f"supported_input_types must be a sequence of strings, got {type(self.supported_input_types)}.")

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")
