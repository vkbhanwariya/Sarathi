"""Pravaha — Dynamic Pipeline Engine for Nabhi Kernel in Sarathi V2.

Defines:
- Pravaha: Executes resolved capability plans across injected executable capabilities.

Executes declared capability plans only; contains no discovery, registration,
device allocation, UI rendering, telemetry persistence, retry, quarantine, or global state.
"""

from __future__ import annotations

from typing import Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.manthan import CapabilityPlan
from sarathi.sankalpa import Capability, ExecutionContext, Request, Result


class Pravaha:
    """Dynamic Pipeline Engine for Nabhi Kernel."""

    def __init__(self, registry: Kosh) -> None:
        if not isinstance(registry, Kosh):
            raise TypeError(f"registry must be a Kosh instance, got {type(registry).__name__}.")
        self._registry: Kosh = registry

    def execute(
        self,
        plan: CapabilityPlan,
        request: Request,
        context: ExecutionContext,
        capabilities: Mapping[str, Capability],
    ) -> Result:
        """Execute a resolved capability plan across provided executable capabilities.

        Validates all planned capabilities against registered declarations before invoking
        the first capability.

        Args:
            plan: The resolved capability execution plan.
            request: The canonical processing request.
            context: The execution context and correlation metadata.
            capabilities: Mapping from capability_id to executable Capability instance.

        Returns:
            The final canonical Result from the pipeline.

        Raises:
            TypeError: If arguments are of invalid types or capabilities do not satisfy protocol.
            DoshError(FailureCode.VALIDATION_FAILED): If plan/request IDs mismatch or declaration mismatch occurs.
            DoshError(FailureCode.DEPENDENCY_UNAVAILABLE): If a planned capability is missing from capabilities mapping.
        """
        # Validate argument types
        if not isinstance(plan, CapabilityPlan):
            raise TypeError(f"plan must be a CapabilityPlan instance, got {type(plan).__name__}.")
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")
        if not isinstance(capabilities, Mapping):
            raise TypeError(f"capabilities must be a Mapping, got {type(capabilities).__name__}.")

        # Validate cross-field request identity consistency
        if plan.request_id != request.request_id:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Plan request_id '{plan.request_id}' does not match request_id '{request.request_id}'.",
            )
        if context.request_id != request.request_id:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Context request_id '{context.request_id}' does not match request_id '{request.request_id}'.",
            )

        # Pre-execution validation: validate all planned capabilities against Kosh and executable bindings
        validated_capabilities: list[Capability] = []
        for cap_id in plan.capability_ids:
            registered_decl = self._registry.get_capability(cap_id)
            if registered_decl is None:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Planned capability '{cap_id}' is not registered in Kosh.",
                )

            if cap_id not in capabilities:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Executable capability '{cap_id}' is not provided in capabilities mapping.",
                )

            executable_cap = capabilities[cap_id]
            if not isinstance(executable_cap, Capability):
                raise TypeError(
                    f"Provided capability '{cap_id}' does not implement Capability protocol, "
                    f"got {type(executable_cap).__name__}."
                )

            if executable_cap.declaration != registered_decl:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Executable capability '{cap_id}' declaration does not match registered declaration in Kosh.",
                )

            validated_capabilities.append(executable_cap)

        # Execute pipeline in plan order
        prior_result: Result | None = None
        for cap in validated_capabilities:
            result = cap.execute(request=request, context=context, prior_result=prior_result)
            if not isinstance(result, Result):
                raise TypeError(
                    f"Capability '{cap.declaration.capability_id}' execute() must return a Result instance, "
                    f"got {type(result).__name__}."
                )
            prior_result = result

        assert prior_result is not None  # plan.capability_ids is guaranteed non-empty by CapabilityPlan contract
        return prior_result
