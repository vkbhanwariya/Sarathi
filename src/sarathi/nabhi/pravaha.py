"""Pravaha - Dynamic Pipeline Engine for Nabhi Kernel in Sarathi V2.

Defines:
- Pravaha: Executes resolved capability plans across injected executable capabilities,
  owns failure lifecycle decisions, bounded retry, quarantine, and release.

Maintains execution control and failure lifecycle; contains no discovery, registration,
device allocation, UI rendering, telemetry persistence, caching, or security policy evaluation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.manthan import CapabilityPlan, Manthan
from sarathi.nabhi.quarantine import (
    LifecycleAction,
    LifecycleActionType,
    QuarantineRecord,
    QuarantineStatus,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import Capability, ExecutionContext, Request, Result
from sarathi.yantra import Yantra

_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class Pravaha:
    """Dynamic Pipeline Engine for Nabhi Kernel owning execution and failure lifecycle."""

    def __init__(
        self,
        manthan: Manthan,
        yantra: Yantra,
        capabilities: Mapping[str, Capability],
        quarantine_store: QuarantineStore | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Initialize Pravaha with resolver, execution manager, capabilities, and optional quarantine store."""
        if not isinstance(manthan, Manthan):
            raise TypeError(f"manthan must be a Manthan instance, got {type(manthan).__name__}.")
        if not isinstance(yantra, Yantra):
            raise TypeError(f"yantra must be a Yantra instance, got {type(yantra).__name__}.")
        if not isinstance(capabilities, Mapping):
            raise TypeError(f"capabilities must be a Mapping, got {type(capabilities).__name__}.")
        if quarantine_store is not None and not isinstance(quarantine_store, QuarantineStore):
            raise TypeError(
                f"quarantine_store must be a QuarantineStore instance or None, got {type(quarantine_store).__name__}."
            )
        if retry_policy is not None and not isinstance(retry_policy, RetryPolicy):
            raise TypeError(f"retry_policy must be a RetryPolicy instance or None, got {type(retry_policy).__name__}.")

        self._manthan: Manthan = manthan
        self._registry: Kosh = manthan.registry
        self._yantra: Yantra = yantra
        self._capabilities: Mapping[str, Capability] = dict(capabilities)
        self._quarantine_store: QuarantineStore | None = quarantine_store
        self._retry_policy: RetryPolicy = retry_policy if retry_policy is not None else RetryPolicy(max_retries=0)

        if self._retry_policy.max_retries > 0 and self._quarantine_store is None:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="Automatic retry policy requires a configured QuarantineStore.",
            )

    @property
    def quarantine_store(self) -> QuarantineStore | None:
        """Return the injected QuarantineStore, if configured."""
        return self._quarantine_store

    @property
    def retry_policy(self) -> RetryPolicy:
        """Return the active RetryPolicy."""
        return self._retry_policy

    def _compute_input_hash(self, request: Request, capability: Capability, context: ExecutionContext) -> str:
        """Compute a deterministic, privacy-safe hash identifying the canonical execution attempt.

        Uses stable factual input identity available in InputRef (input_id, display_name,
        size_bytes, media_type) in deterministic input order without persisting raw filesystem paths.
        """
        input_material = "|".join(
            f"{inp.input_id}:{inp.display_name}:{inp.size_bytes}:{inp.media_type or ''}"
            for inp in request.inputs
        )
        content = (
            f"{context.run_id}:{request.request_id}:{capability.declaration.capability_id}:"
            f"{context.profile.value}:{input_material}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _execute_retry_attempt(
        self,
        cap: Capability,
        request: Request,
        context: ExecutionContext,
        record: QuarantineRecord,
        prior_result: Result | None = None,
    ) -> tuple[Result | None, QuarantineRecord]:
        """Execute one retry attempt through Yantra with full failure lifecycle handling.

        1. Validates current record/state.
        2. Validates retry eligibility.
        3. Increments factual attempt count.
        4. Executes through Yantra.
        5. On success -> marks RELEASED in QuarantineStore.
        6. On classified failure -> updates attempt/persists TERMINAL state when exhausted.
        7. Preserves original Dosh classification when failure remains terminal.

        Returns:
            Tuple of (Result, updated QuarantineRecord) on success.

        Raises:
            DoshError: If retry attempt fails.
        """
        if self._quarantine_store is None:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="No quarantine store configured in Pravaha.",
            )

        if record.status == QuarantineStatus.TERMINAL:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{record.quarantine_id}' is in terminal state and cannot be retried.",
            )
        if record.status == QuarantineStatus.RELEASED:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{record.quarantine_id}' is already released.",
            )
        if record.attempt_count >= record.max_retries:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{record.quarantine_id}' has exhausted maximum retries ({record.max_retries}).",
            )

        new_attempt = record.attempt_count + 1

        # Mark attempt as actively being retried in store
        retried_rec = self._quarantine_store.update_status(
            record.quarantine_id,
            QuarantineStatus.RETRIED,
            attempt_count=new_attempt,
        )

        retry_ctx = ExecutionContext(
            run_id=context.run_id,
            request_id=context.request_id,
            trace_id=context.trace_id,
            span_id=f"retry-{new_attempt}-{context.span_id}",
            parent_span_id=context.span_id,
            profile=context.profile,
            quarantine_attempt=new_attempt,
            is_retry=True,
            metadata=context.metadata,
        )

        try:
            result = self._yantra.execute(
                capability=cap,
                request=request,
                context=retry_ctx,
                prior_result=prior_result,
            )
            # Retry succeeded: release quarantined status
            released_rec = self._quarantine_store.update_status(
                record.quarantine_id,
                QuarantineStatus.RELEASED,
                attempt_count=new_attempt,
            )
            return result, released_rec
        except DoshError as dosh_err:
            # Check if this failure remains retryable and retries are not exhausted
            if self._retry_policy.is_retryable(dosh_err.code, new_attempt):
                # Update failure code and keep in RETRIED state with new attempt count
                ts_now = datetime.now(timezone.utc).isoformat()
                interim_rec = QuarantineRecord(
                    quarantine_id=retried_rec.quarantine_id,
                    input_hash=retried_rec.input_hash,
                    run_id=retried_rec.run_id,
                    request_id=retried_rec.request_id,
                    trace_id=retried_rec.trace_id,
                    capability_id=retried_rec.capability_id,
                    plugin_id=retried_rec.plugin_id,
                    failure_code=dosh_err.code,
                    profile=retried_rec.profile,
                    attempt_count=new_attempt,
                    max_retries=retried_rec.max_retries,
                    status=QuarantineStatus.RETRIED,
                    created_at_utc=retried_rec.created_at_utc,
                    updated_at_utc=ts_now,
                    provenance=retried_rec.provenance,
                )
                self._quarantine_store.quarantine(interim_rec)
            else:
                # Retries exhausted or non-retryable error: transition to TERMINAL
                ts_now = datetime.now(timezone.utc).isoformat()
                term_rec = QuarantineRecord(
                    quarantine_id=retried_rec.quarantine_id,
                    input_hash=retried_rec.input_hash,
                    run_id=retried_rec.run_id,
                    request_id=retried_rec.request_id,
                    trace_id=retried_rec.trace_id,
                    capability_id=retried_rec.capability_id,
                    plugin_id=retried_rec.plugin_id,
                    failure_code=dosh_err.code,
                    profile=retried_rec.profile,
                    attempt_count=new_attempt,
                    max_retries=retried_rec.max_retries,
                    status=QuarantineStatus.TERMINAL,
                    created_at_utc=retried_rec.created_at_utc,
                    updated_at_utc=ts_now,
                    provenance=retried_rec.provenance,
                )
                self._quarantine_store.quarantine(term_rec)
            raise dosh_err

    def execute(
        self,
        plan: CapabilityPlan,
        request: Request,
        context: ExecutionContext,
    ) -> Result:
        """Execute a resolved capability plan across configured capabilities through Yantra.

        Validates all planned capabilities against registered declarations before invoking
        capabilities through Yantra. Dynamically resolves and continues execution if a capability
        returns a next_requirement handoff. Handles classified failures through bounded retry and quarantine.

        Args:
            plan: The resolved capability execution plan.
            request: The canonical processing request.
            context: The execution context and correlation metadata.

        Returns:
            The final canonical Result from the pipeline.

        Raises:
            TypeError: If arguments are of invalid types or capabilities do not satisfy protocol.
            DoshError(FailureCode.VALIDATION_FAILED): If plan/request IDs mismatch, declaration mismatch occurs,
                a repeated requirement is encountered, or a terminal attempt is re-executed.
            DoshError(FailureCode.DEPENDENCY_UNAVAILABLE): If a planned capability is missing from capabilities mapping.
            DoshError: On unrecoverable or exhausted capability execution failure.
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

            # Execute pipeline in plan order through Yantra with failure lifecycle handling
            for cap in validated_capabilities:
                current_ctx = context
                input_hash = self._compute_input_hash(current_request, cap, current_ctx)
                quar_id = f"quar-{input_hash[:16]}"

                # Check if attempt is already terminal in quarantine
                if self._quarantine_store is not None:
                    existing_rec = self._quarantine_store.get_record(quar_id)
                    if existing_rec is not None and existing_rec.status == QuarantineStatus.TERMINAL:
                        raise DoshError(
                            code=FailureCode.VALIDATION_FAILED,
                            message=f"Attempt for capability '{cap.declaration.capability_id}' is in terminal quarantine state and cannot be executed again.",
                        )

                try:
                    prior_result = self._yantra.execute(
                        capability=cap,
                        request=current_request,
                        context=current_ctx,
                        prior_result=prior_result,
                    )
                except DoshError as dosh_err:
                    current_attempt = 0
                    is_retry_allowed = self._retry_policy.is_retryable(dosh_err.code, current_attempt)

                    if not is_retry_allowed:
                        # Non-retryable or zero-retries policy: mark terminal quarantine if store configured
                        if self._quarantine_store is not None:
                            rec = QuarantineRecord(
                                quarantine_id=quar_id,
                                input_hash=input_hash,
                                run_id=current_ctx.run_id,
                                request_id=current_ctx.request_id,
                                trace_id=current_ctx.trace_id,
                                capability_id=cap.declaration.capability_id,
                                plugin_id=cap.declaration.plugin_id,
                                failure_code=dosh_err.code,
                                profile=current_ctx.profile.value,
                                attempt_count=current_attempt,
                                max_retries=self._retry_policy.max_retries,
                                status=QuarantineStatus.TERMINAL,
                                created_at_utc=datetime.now(timezone.utc).isoformat(),
                                updated_at_utc=datetime.now(timezone.utc).isoformat(),
                            )
                            self._quarantine_store.quarantine(rec)
                        raise dosh_err

                    # Retry is allowed: initialize quarantine record and loop through canonical retry path
                    init_rec = QuarantineRecord(
                        quarantine_id=quar_id,
                        input_hash=input_hash,
                        run_id=current_ctx.run_id,
                        request_id=current_ctx.request_id,
                        trace_id=current_ctx.trace_id,
                        capability_id=cap.declaration.capability_id,
                        plugin_id=cap.declaration.plugin_id,
                        failure_code=dosh_err.code,
                        profile=current_ctx.profile.value,
                        attempt_count=current_attempt,
                        max_retries=self._retry_policy.max_retries,
                        status=QuarantineStatus.QUARANTINED,
                        created_at_utc=datetime.now(timezone.utc).isoformat(),
                        updated_at_utc=datetime.now(timezone.utc).isoformat(),
                    )
                    assert self._quarantine_store is not None  # Enforced by __init__ when max_retries > 0
                    self._quarantine_store.quarantine(init_rec)

                    curr_rec = init_rec
                    last_err: DoshError = dosh_err
                    while self._retry_policy.is_retryable(last_err.code, curr_rec.attempt_count):
                        try:
                            retry_res, updated_rec = self._execute_retry_attempt(
                                cap=cap,
                                request=current_request,
                                context=current_ctx,
                                record=curr_rec,
                                prior_result=prior_result,
                            )
                            prior_result = retry_res
                            break
                        except DoshError as retry_err:
                            last_err = retry_err
                            curr_rec = self._quarantine_store.get_record(curr_rec.quarantine_id) or curr_rec
                            if not self._retry_policy.is_retryable(last_err.code, curr_rec.attempt_count):
                                raise retry_err

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

    def apply_lifecycle_action(
        self,
        action: LifecycleAction,
        *,
        request: Request | None = None,
        plan: CapabilityPlan | None = None,
        context: ExecutionContext | None = None,
    ) -> QuarantineRecord:
        """Apply a validated lifecycle transition (release, retry, terminate) to a quarantined item.

        Args:
            action: Typed LifecycleAction request.
            request: Optional Request override for retry re-execution.
            plan: Optional CapabilityPlan override for retry re-execution.
            context: Optional ExecutionContext override for retry re-execution.

        Returns:
            The updated QuarantineRecord.

        Raises:
            TypeError: If action is not a LifecycleAction instance.
            DoshError(FailureCode.INVALID_CONFIGURATION): If no QuarantineStore is configured.
            DoshError(FailureCode.VALIDATION_FAILED): If transition is invalid, item ID is malformed,
                item does not exist, or required execution context is missing.
            DoshError(FailureCode.DEPENDENCY_UNAVAILABLE): If capability required for retry is missing.
        """
        if not isinstance(action, LifecycleAction):
            raise TypeError(f"action must be a LifecycleAction instance, got {type(action).__name__}.")

        if self._quarantine_store is None:
            raise DoshError(
                code=FailureCode.INVALID_CONFIGURATION,
                message="No quarantine store configured in Pravaha.",
            )

        # Validate action item_id format
        if not isinstance(action.item_id, str) or not _SAFE_ID_PATTERN.match(action.item_id):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Invalid quarantine item identifier format.",
            )

        existing = self._quarantine_store.get_record(action.item_id)
        if existing is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Quarantine item '{action.item_id}' not found.",
            )

        if action.action == LifecycleActionType.RELEASE:
            if existing.status == QuarantineStatus.RELEASED:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' is already released.",
                )
            if existing.status == QuarantineStatus.TERMINAL:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' is in terminal state and cannot be released.",
                )
            return self._quarantine_store.update_status(action.item_id, QuarantineStatus.RELEASED)

        elif action.action == LifecycleActionType.TERMINATE:
            if existing.status == QuarantineStatus.TERMINAL:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' is already terminal.",
                )
            if existing.status == QuarantineStatus.RELEASED:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' is in released state and cannot be terminated.",
                )
            return self._quarantine_store.update_status(action.item_id, QuarantineStatus.TERMINAL)

        elif action.action == LifecycleActionType.RETRY:
            if existing.status == QuarantineStatus.TERMINAL:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' is in terminal state and cannot be retried.",
                )
            if existing.status == QuarantineStatus.RELEASED:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' is already released.",
                )
            if existing.attempt_count >= existing.max_retries:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Quarantine item '{action.item_id}' has exhausted maximum retries ({existing.max_retries}).",
                )

            effective_req = request if request is not None else action.request
            effective_ctx = context if context is not None else action.context

            if effective_req is None or effective_ctx is None:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="Request and ExecutionContext are required to execute a retry through Yantra.",
                )

            cap_id = existing.capability_id
            if cap_id not in self._capabilities:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Executable capability '{cap_id}' is not available in Pravaha capabilities.",
                )
            cap = self._capabilities[cap_id]

            _, updated_rec = self._execute_retry_attempt(
                cap=cap,
                request=effective_req,
                context=effective_ctx,
                record=existing,
            )
            return updated_rec
