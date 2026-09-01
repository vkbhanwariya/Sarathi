"""Manthan — Capability Resolver for Nabhi Kernel in Sarathi V2.

Defines:
- CapabilityPlan: Immutable resolved capability execution plan.
- Manthan: Domain-neutral capability resolver resolving requests against registered declarations.

Resolves declarations only; contains no execution, discovery, lifecycle work,
resource allocation, telemetry, retry, quarantine, caching, or security enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.sankalpa import CapabilityDeclaration, Request


@dataclass(frozen=True, slots=True)
class CapabilityPlan:
    """Immutable resolved capability execution plan."""

    request_id: str
    capability_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string.")

        if isinstance(self.capability_ids, set):
            raise TypeError("capability_ids must be an ordered sequence (list or tuple), not a set.")
        if not isinstance(self.capability_ids, (list, tuple)):
            raise TypeError(f"capability_ids must be an ordered sequence of strings, got {type(self.capability_ids)}.")
        if not self.capability_ids:
            raise ValueError("capability_ids cannot be empty.")

        cleaned_ids: list[str] = []
        for i, cid in enumerate(self.capability_ids):
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError(f"capability_ids[{i}] must be a non-empty string.")
            cleaned_ids.append(cid.strip())

        object.__setattr__(self, "capability_ids", tuple(cleaned_ids))


class Manthan:
    """Domain-neutral capability resolver for Nabhi Kernel."""

    def __init__(self, registry: Kosh) -> None:
        if not isinstance(registry, Kosh):
            raise TypeError(f"registry must be a Kosh instance, got {type(registry).__name__}.")
        self._registry: Kosh = registry

    def resolve(self, request: Request) -> CapabilityPlan:
        """Resolve a deterministic capability plan for a request against registered capabilities.

        Phase 1 routing:
        - `request.requirement` matches `CapabilityDeclaration.capability_id`.
        - `request.profile` must be supported by the capability.
        - If `capability.supported_input_types` is declared, every input must have a matching `media_type`.

        Raises:
            TypeError: If request is of invalid type.
            DoshError(FailureCode.UNSUPPORTED): If no compatible capability is declared.
        """
        # Validate public arguments before accessing registry state
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")

        requirement = request.requirement
        capability = self._registry.get_capability(requirement)

        if capability is None:
            raise DoshError(
                code=FailureCode.UNSUPPORTED,
                message=f"No capability registered for requirement '{requirement}'.",
            )

        # Validate requested execution profile
        if request.profile not in capability.supported_profiles:
            raise DoshError(
                code=FailureCode.UNSUPPORTED,
                message=(
                    f"Capability '{capability.capability_id}' does not support requested "
                    f"execution profile '{request.profile.value}'."
                ),
            )

        # Validate input media types if supported_input_types is declared
        if capability.supported_input_types:
            for inp in request.inputs:
                if not inp.media_type or not inp.media_type.strip():
                    raise DoshError(
                        code=FailureCode.UNSUPPORTED,
                        message=(
                            f"Input '{inp.input_id}' is missing media_type required by "
                            f"capability '{capability.capability_id}'."
                        ),
                    )

                normalized_media_type = inp.media_type.strip().lower()
                if normalized_media_type not in capability.supported_input_types:
                    raise DoshError(
                        code=FailureCode.UNSUPPORTED,
                        message=(
                            f"Input '{inp.input_id}' media type '{inp.media_type}' is not "
                            f"supported by capability '{capability.capability_id}'."
                        ),
                    )

        return CapabilityPlan(
            request_id=request.request_id,
            capability_ids=(capability.capability_id,),
        )
