"""Manthan — Capability Resolver for Nabhi Kernel in Sarathi.

Defines:
- CapabilityPlan: Immutable resolved capability execution plan.
- Manthan: Domain-neutral capability resolver resolving requests against registered declarations.

Resolves declarations only; contains no execution, discovery, lifecycle work,
resource allocation, telemetry, retry, quarantine, caching, or security enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Collection, Sequence

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.sankalpa import ExecutionProfile, Request


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
        seen_ids: set[str] = set()
        for i, cid in enumerate(self.capability_ids):
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError(f"capability_ids[{i}] must be a non-empty string.")
            s_cid = cid.strip()
            if s_cid in seen_ids:
                raise ValueError(f"Duplicate capability stage '{s_cid}' in CapabilityPlan is prohibited.")
            seen_ids.add(s_cid)
            cleaned_ids.append(s_cid)

        object.__setattr__(self, "capability_ids", tuple(cleaned_ids))


class Manthan:
    """Domain-neutral capability resolver for Nabhi Kernel."""

    def __init__(self, registry: Kosh) -> None:
        if not isinstance(registry, Kosh):
            raise TypeError(f"registry must be a Kosh instance, got {type(registry).__name__}.")
        self._registry: Kosh = registry

    @property
    def registry(self) -> Kosh:
        """Return the injected canonical Kosh registry."""
        return self._registry

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

        planned_ids = self._topological_sort(capability.capability_id, request.profile)

        return CapabilityPlan(
            request_id=request.request_id,
            capability_ids=planned_ids,
        )

    def resolve_continuation(
        self,
        request: Request,
        next_requirement: str,
        *,
        completed_capability_ids: Collection[str] = (),
        remaining_capability_ids: Sequence[str] = (),
    ) -> tuple[Request, CapabilityPlan]:
        """Resolve a continuation while preserving the request's execution profile.

        Completed prerequisite stages are removed from the newly resolved route,
        then still-pending stages from the interrupted plan are appended in order.
        Manthan remains the only component that constructs continuation plans.
        """
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(next_requirement, str):
            raise TypeError(f"next_requirement must be a string, got {type(next_requirement).__name__}.")

        continuation_request = replace(request, requirement=next_requirement)
        next_plan = self.resolve(continuation_request)
        completed = set(completed_capability_ids)

        combined_stages: list[str] = []
        for capability_id in next_plan.capability_ids:
            if capability_id not in completed and capability_id not in combined_stages:
                combined_stages.append(capability_id)
        for capability_id in remaining_capability_ids:
            if capability_id not in combined_stages:
                combined_stages.append(capability_id)

        return continuation_request, CapabilityPlan(
            request_id=request.request_id,
            capability_ids=tuple(combined_stages),
        )

    def _topological_sort(self, root_id: str, profile: ExecutionProfile | None = None) -> tuple[str, ...]:
        """Perform recursive topological sort resolving all transitive prerequisites.

        Detects and rejects cycles (A -> B -> A), self-prerequisites (A -> A),
        and prerequisite capabilities lacking support for the requested execution profile,
        while safely pruning redundant transitive dependencies.
        """
        order: list[str] = []
        visiting: list[str] = []
        visited: set[str] = set()

        def dfs(cap_id: str) -> None:
            if cap_id in visiting:
                cycle_str = " -> ".join(visiting + [cap_id])
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Circular prerequisite dependency cycle detected: {cycle_str}.",
                )
            if cap_id in visited:
                return

            cap = self._registry.get_capability(cap_id)
            if cap is None:
                parent = visiting[-1] if visiting else root_id
                raise DoshError(
                    code=FailureCode.UNSUPPORTED,
                    message=f"Prerequisite capability '{cap_id}' required by '{parent}' is not registered.",
                )

            if profile is not None and profile not in cap.supported_profiles:
                if visiting:
                    parent = visiting[-1]
                    message = (
                        f"Prerequisite capability '{cap_id}' required by '{parent}' does not support "
                        f"requested execution profile '{profile.value}'."
                    )
                else:
                    message = (
                        f"Capability '{cap_id}' does not support requested "
                        f"execution profile '{profile.value}'."
                    )
                raise DoshError(code=FailureCode.UNSUPPORTED, message=message)

            if cap_id in cap.prerequisites:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Self-prerequisite detected: capability '{cap_id}' cannot depend on itself.",
                )

            visiting.append(cap_id)
            for prereq in cap.prerequisites:
                if not prereq or not isinstance(prereq, str):
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Invalid prerequisite identifier '{prereq}' in capability '{cap_id}'.",
                    )
                dfs(prereq)
            visiting.pop()

            visited.add(cap_id)
            order.append(cap_id)

        dfs(root_id)
        return tuple(order)
