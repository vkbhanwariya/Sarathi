"""Pravaha — Dynamic Pipeline Engine for Nabhi Kernel in Sarathi V2.

Defines:
- Pravaha: Executes resolved capability plans across injected executable capabilities with dynamic next-requirement handoff.

Executes declared capability plans only; contains no discovery, registration,
device allocation, UI rendering, telemetry persistence, retry, quarantine, or global state.
"""

from __future__ import annotations

from typing import Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.manthan import CapabilityPlan, Manthan
from sarathi.sankalpa import Capability, ExecutionContext, Request, Result
from sarathi.yantra import Yantra


class Pravaha:
    """Dynamic Pipeline Engine for Nabhi Kernel."""

    def __init__(
        self,
        manthan: Manthan,
        yantra: Yantra,
        capabilities: Mapping[str, Capability],
    ) -> None:
        if not isinstance(manthan, Manthan):
            raise TypeError(f"manthan must be a Manthan instance, got {type(manthan).__name__}.")
        if not isinstance(yantra, Yantra):
            raise TypeError(f"yantra must be a Yantra instance, got {type(yantra).__name__}.")
        if not isinstance(capabilities, Mapping):
            raise TypeError(f"capabilities must be a Mapping, got {type(capabilities).__name__}.")

        self._manthan: Manthan = manthan
        self._registry: Kosh = manthan.registry
        self._yantra: Yantra = yantra
        self._capabilities: Mapping[str, Capability] = dict(capabilities)

    def execute(
        self,
        plan: CapabilityPlan,
        request: Request,
        context: ExecutionContext,
    ) -> Result:
        """Execute a resolved capability plan across configured capabilities through Yantra.

        Validates all planned capabilities against registered declarations before invoking
        capabilities through Yantra. Dynamically resolves and continues execution if a capability
        returns a next_requirement handoff.

        Args:
            plan: The resolved capability execution plan.
            request: The canonical processing request.
            context: The execution context and correlation metadata.

        Returns:
            The final canonical Result from the pipeline.

        Raises:
            TypeError: If arguments are of invalid types or capabilities do not satisfy protocol.
            DoshError(FailureCode.VALIDATION_FAILED): If plan/request IDs mismatch, declaration mismatch occurs,
                or a repeated requirement is encountered during handoff.
            DoshError(FailureCode.DEPENDENCY_UNAVAILABLE): If a planned capability is missing from capabilities mapping.
        """
        # Validate argument types
        if not isinstance(plan, CapabilityPlan):
            raise TypeError(f"plan must be a CapabilityPlan instance, got {type(plan).__name__}.")
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

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

        current_plan: CapabilityPlan = plan
        current_request: Request = request
        prior_result: Result | None = None
        seen_requirements: set[str] = {request.requirement}

        while True:
            # Pre-execution validation: validate all planned capabilities against Kosh and executable bindings
            validated_capabilities: list[Capability] = []
            for cap_id in current_plan.capability_ids:
                registered_decl = self._registry.get_capability(cap_id)
                if registered_decl is None:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Planned capability '{cap_id}' is not registered in Kosh.",
                    )

                if cap_id not in self._capabilities:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Executable capability '{cap_id}' is not provided in capabilities mapping.",
                    )

                executable_cap = self._capabilities[cap_id]
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

            # Execute pipeline in plan order through Yantra
            for cap in validated_capabilities:
                prior_result = self._yantra.execute(
                    capability=cap,
                    request=current_request,
                    context=context,
                    prior_result=prior_result,
                )

                if prior_result.next_requirement is not None:
                    break

            assert prior_result is not None  # plan.capability_ids is guaranteed non-empty by CapabilityPlan contract

            # Normal final result
            if prior_result.next_requirement is None:
                return prior_result

            next_req_id = prior_result.next_requirement
            if next_req_id in seen_requirements:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Repeated requirement '{next_req_id}' in pipeline execution is rejected.",
                )
            seen_requirements.add(next_req_id)

            # Construct next Request with updated requirement
            current_request = Request(
                request_id=current_request.request_id,
                requirement=next_req_id,
                inputs=current_request.inputs,
                profile=current_request.profile,
                custom_options=current_request.custom_options,
                output_root=current_request.output_root,
                preserve_partial=current_request.preserve_partial,
                metadata=current_request.metadata,
            )

            # Resolve next plan through Manthan
            current_plan = self._manthan.resolve(current_request)
