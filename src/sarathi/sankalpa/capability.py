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
from typing import TYPE_CHECKING, Any, Mapping, Protocol, runtime_checkable

from sarathi.sankalpa.execution_profile import ExecutionProfile

if TYPE_CHECKING:
    from sarathi.sankalpa.context import ExecutionContext
    from sarathi.sankalpa.request import Request
    from sarathi.sankalpa.result import Result


@runtime_checkable
class Capability(Protocol):
    """Canonical executable Capability protocol for Sarathi V2.

    The single canonical interface for executable plugin capabilities in Shakti.
    Exposes an immutable declaration and an execute method transforming an input
    request and execution context into a canonical Result.
    """

    @property
    def declaration(self) -> CapabilityDeclaration:
        """Declared capability metadata and execution preferences."""
        ...

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute capability logic on the provided request and context.

        Args:
            request: The canonical processing request.
            context: The runtime execution context and tracing metadata.
            prior_result: Optional result from a preceding pipeline stage (None if first stage).

        Returns:
            Canonical Result containing document data, typed artifact payloads, confidence, and provenance.
        """
        ...


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
        raise ValueError(f"Invalid device type: {value!r}. Allowed devices: {[d.value for d in cls]}")


@dataclass(frozen=True, slots=True)
class DeviceRequirement:
    """Declared execution hardware requirements."""

    preferred_devices: tuple[DeviceType, ...] = (DeviceType.CPU,)
    supported_devices: tuple[DeviceType, ...] = (DeviceType.CPU,)
    parallelizable: bool = True
    estimated_memory_bytes: int | None = None
    priority: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.preferred_devices, set):
            raise TypeError("preferred_devices must be an ordered sequence (list or tuple), not a set.")
        if not isinstance(self.preferred_devices, (list, tuple)):
            raise TypeError(f"preferred_devices must be a sequence of DeviceType, got {type(self.preferred_devices)}.")

        if isinstance(self.supported_devices, set):
            raise TypeError("supported_devices must be an ordered sequence (list or tuple), not a set.")
        if not isinstance(self.supported_devices, (list, tuple)):
            raise TypeError(f"supported_devices must be a sequence of DeviceType, got {type(self.supported_devices)}.")

        if not self.preferred_devices:
            raise ValueError("preferred_devices cannot be empty.")
        if not self.supported_devices:
            raise ValueError("supported_devices cannot be empty.")

        # Parse & validate supported devices
        supported: list[DeviceType] = []
        seen_supported: set[DeviceType] = set()
        for d in self.supported_devices:
            dev = d if isinstance(d, DeviceType) else DeviceType.from_string(str(d))
            if dev in seen_supported:
                raise ValueError(f"Duplicate device in supported_devices: {dev.value}")
            seen_supported.add(dev)
            supported.append(dev)
        object.__setattr__(self, "supported_devices", tuple(supported))

        # Parse & validate preferred devices
        preferred: list[DeviceType] = []
        seen_preferred: set[DeviceType] = set()
        for d in self.preferred_devices:
            dev = d if isinstance(d, DeviceType) else DeviceType.from_string(str(d))
            if dev in seen_preferred:
                raise ValueError(f"Duplicate device in preferred_devices: {dev.value}")
            if dev not in seen_supported:
                raise ValueError(
                    f"Preferred device {dev.value!r} must also be in supported_devices: {[s.value for s in supported]}"
                )
            seen_preferred.add(dev)
            preferred.append(dev)
        object.__setattr__(self, "preferred_devices", tuple(preferred))

        if self.estimated_memory_bytes is not None and self.estimated_memory_bytes < 0:
            raise ValueError(f"estimated_memory_bytes cannot be negative (got {self.estimated_memory_bytes}).")


@dataclass(frozen=True, slots=True)
class CapabilityDeclaration:
    """Canonical capability declaration registered with Nabhi."""

    capability_id: str
    plugin_id: str
    version: str
    supported_profiles: tuple[ExecutionProfile, ...]
    description: str = ""
    device_requirement: DeviceRequirement = field(default_factory=DeviceRequirement)
    supported_input_types: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()
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

        if isinstance(self.supported_profiles, set):
            raise TypeError("supported_profiles must be an ordered sequence (list or tuple), not a set.")
        if not isinstance(self.supported_profiles, (list, tuple)):
            raise TypeError(
                f"supported_profiles must be a sequence of ExecutionProfile, got {type(self.supported_profiles)}."
            )
        if not self.supported_profiles:
            raise ValueError(
                "supported_profiles cannot be empty; capabilities must explicitly declare their supported profiles."
            )

        profiles: list[ExecutionProfile] = []
        seen_profiles: set[ExecutionProfile] = set()
        for p in self.supported_profiles:
            prof = p if isinstance(p, ExecutionProfile) else ExecutionProfile.from_string(str(p))
            if prof in seen_profiles:
                raise ValueError(f"Duplicate profile in supported_profiles: {prof.value}")
            seen_profiles.add(prof)
            profiles.append(prof)
        object.__setattr__(self, "supported_profiles", tuple(profiles))

        if isinstance(self.supported_input_types, (list, tuple)):
            cleaned_inputs = tuple(t.strip().lower() for t in self.supported_input_types if t and t.strip())
            object.__setattr__(self, "supported_input_types", cleaned_inputs)
        else:
            raise TypeError(
                f"supported_input_types must be a sequence of strings, got {type(self.supported_input_types)}."
            )

        if isinstance(self.prerequisites, (list, tuple)):
            cleaned_prereqs = tuple(p.strip() for p in self.prerequisites if p and p.strip())
            object.__setattr__(self, "prerequisites", cleaned_prereqs)
        else:
            raise TypeError(f"prerequisites must be a sequence of strings, got {type(self.prerequisites)}.")

        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        else:
            raise TypeError(f"metadata must be a Mapping, got {type(self.metadata)}.")
