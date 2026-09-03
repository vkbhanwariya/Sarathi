"""Pravaha - Dynamic Pipeline Engine for Nabhi Kernel in Sarathi V2.

Defines:
- Pravaha: Executes resolved capability plans across injected executable capabilities,
  owns failure lifecycle decisions, bounded retry, quarantine, and release.

Maintains execution control and failure lifecycle; contains no discovery, registration,
device allocation, UI rendering, telemetry persistence, caching, or security policy evaluation.
"""

from __future__ import annotations

import hashlib
import re
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

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
from sarathi.smriti import SmritiCache, compute_cache_key, compute_input_fingerprint
from sarathi.yantra import Yantra

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.kavacha import Kavacha

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
        darpana: Darpana | None = None,
        kavacha: Kavacha | None = None,
        smriti: SmritiCache | None = None,
    ) -> None:
        """Initialize Pravaha with resolver, execution manager, capabilities, optional quarantine, and telemetry."""
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
        if darpana is not None:
            from sarathi.darpana import Darpana as DarpanaService

            if not isinstance(darpana, DarpanaService):
                raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")
        if kavacha is not None:
            from sarathi.kavacha import Kavacha as KavachaService

            if not isinstance(kavacha, KavachaService):
                raise TypeError(f"kavacha must be a Kavacha instance or None, got {type(kavacha).__name__}.")

        self._manthan: Manthan = manthan
        self._registry: Kosh = manthan.registry
        self._yantra: Yantra = yantra
        self._capabilities: Mapping[str, Capability] = dict(capabilities)
        self._quarantine_store: QuarantineStore | None = quarantine_store
        self._retry_policy: RetryPolicy = retry_policy if retry_policy is not None else RetryPolicy(max_retries=0)
        self._darpana: Darpana | None = darpana
        self._kavacha: Kavacha | None = kavacha
        if smriti is not None and not isinstance(smriti, SmritiCache):
            raise TypeError(f"smriti must be a SmritiCache instance or None, got {type(smriti).__name__}.")
        self._smriti: SmritiCache | None = smriti

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

    @property
    def darpana(self) -> Darpana | None:
        """Return the injected Darpana telemetry service, if configured."""
        return self._darpana

    @property
    def kavacha(self) -> Kavacha | None:
        """Return the injected Kavacha security service, if configured."""
        return self._kavacha

    def _authorize_capability(self, cap: Capability) -> None:
        """Authorize capability's owning plugin security declaration via Kavacha if configured."""
        if self._kavacha is not None:
            plugin = self._registry.get_plugin(cap.declaration.plugin_id)
            if plugin is not None:
                self._kavacha.authorize(plugin.security)

    def _compute_input_hash(self, request: Request, capability: Capability, context: ExecutionContext) -> str:
        """Compute a deterministic, privacy-safe hash identifying the canonical execution attempt.

        Reuses the canonical input fingerprint from Smriti combined with execution scope.
        """
        fingerprint = compute_input_fingerprint(request.inputs)
        content = (
            f"{context.run_id}:{request.request_id}:{capability.declaration.capability_id}:"
            f"{context.profile.value}:{fingerprint}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _record_pramana_if_available(
        self,
        capability: Capability,
        result: Result,
        context: ExecutionContext,
    ) -> None:
        """Record quality observation to Darpana Pramana telemetry if evidence-backed facts exist."""
        if self._darpana is None:
            return

        from sarathi.darpana import AccuracyValue, PramanaRecord

        accuracy_val = (
            result.metadata.get("accuracy") if isinstance(result.metadata.get("accuracy"), AccuracyValue) else None
        )

        if result.confidence is not None or accuracy_val is not None:
            pramana_rec = PramanaRecord(
                run_id=context.run_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                span_id=context.span_id,
                capability_id=capability.declaration.capability_id,
                stage=capability.declaration.capability_id,
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                confidence=result.confidence,
                accuracy=accuracy_val,
                attributes={
                    "plugin_id": capability.declaration.plugin_id,
                    "profile": context.profile.value,
                },
            )
            self._darpana.record_pramana(pramana_rec)

    def _quarantine_transition_scope(
        self,
        context: ExecutionContext,
        capability_id: str,
        lifecycle_status: str,
        attempt_count: int,
        max_retries: int,
    ):
        """Timing scope for actual quarantine lifecycle state transitions."""
        if self._darpana is not None:
            return self._darpana.time_scope(
                context=context,
                phase_name="quarantine_lifecycle",
                component="nabhi.pravaha",
                attributes={
                    "capability_id": capability_id,
                    "lifecycle_status": lifecycle_status,
                    "attempt_count": attempt_count,
                    "max_retries": max_retries,
                },
            )
        return nullcontext()

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
        3. Authorizes capability through Kavacha.
        4. Increments factual attempt count.
        5. Executes through Yantra.
        6. On success -> marks RELEASED in QuarantineStore.
        7. On classified failure -> updates attempt/persists TERMINAL state when exhausted.
        8. Preserves original Dosh classification when failure remains terminal.

        Returns:
            Tuple of (Result, updated QuarantineRecord) on success.

        Raises:
            DoshError: If retry attempt fails or security authorization is denied.
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

        # Enforce security authorization before any retry mutation or Yantra allocation
        self._authorize_capability(cap)

        # Check cancellation before retry execution; cancellation bypasses retry
        if request.cancellation_token is not None and request.cancellation_token.is_cancelled:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Execution was cancelled before retry attempt.",
                context={"cancelled": True},
            )
        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Execution was cancelled before retry attempt.",
                context={"cancelled": True},
            )

        new_attempt = record.attempt_count + 1

        # Mark attempt as actively being retried in store with measured lifecycle time_scope
        with self._quarantine_transition_scope(
            context=context,
            capability_id=record.capability_id,
            lifecycle_status=QuarantineStatus.RETRIED.value,
            attempt_count=new_attempt,
            max_retries=record.max_retries,
        ):
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
            cancellation_token=context.cancellation_token or request.cancellation_token,
            metadata=context.metadata,
        )

        scope = (
            self._darpana.time_scope(
                context=retry_ctx,
                phase_name="retry_attempt",
                component="nabhi.pravaha",
                attributes={
                    "capability_id": cap.declaration.capability_id,
                    "attempt": new_attempt,
                    "max_retries": record.max_retries,
                },
            )
            if self._darpana is not None
            else nullcontext()
        )

        try:
            with scope:
                result = self._yantra.execute(
                    capability=cap,
                    request=request,
                    context=retry_ctx,
                    prior_result=prior_result,
                )

            # Retry succeeded: release quarantined status with measured lifecycle time_scope
            with self._quarantine_transition_scope(
                context=retry_ctx,
                capability_id=record.capability_id,
                lifecycle_status=QuarantineStatus.RELEASED.value,
                attempt_count=new_attempt,
                max_retries=record.max_retries,
            ):
                released_rec = self._quarantine_store.update_status(
                    record.quarantine_id,
                    QuarantineStatus.RELEASED,
                    attempt_count=new_attempt,
                )
            self._record_pramana_if_available(cap, result, retry_ctx)
            return result, released_rec
        except DoshError as dosh_err:
            # Check if this failure remains retryable and retries are not exhausted
            is_still_retryable = self._retry_policy.is_retryable(dosh_err.code, new_attempt)
            next_status = QuarantineStatus.RETRIED if is_still_retryable else QuarantineStatus.TERMINAL
            ts_now = datetime.now(timezone.utc).isoformat()

            updated_rec = QuarantineRecord(
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
                status=next_status,
                created_at_utc=retried_rec.created_at_utc,
                updated_at_utc=ts_now,
                provenance=retried_rec.provenance,
            )
            if not is_still_retryable:
                with self._quarantine_transition_scope(
                    context=retry_ctx,
                    capability_id=updated_rec.capability_id,
                    lifecycle_status=QuarantineStatus.TERMINAL.value,
                    attempt_count=updated_rec.attempt_count,
                    max_retries=updated_rec.max_retries,
                ):
                    self._quarantine_store.quarantine(updated_rec)
            else:
                self._quarantine_store.quarantine(updated_rec)
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
            DoshError(FailureCode.SECURITY_DENIED): If capability violates Kavacha security authorization.
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
        completed_capability_ids: set[str] = set()

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

                # Authorize against Kavacha before execution
                self._authorize_capability(executable_cap)

                validated_capabilities.append(executable_cap)

            # Execute pipeline in plan order through Yantra with failure lifecycle handling
            executed_stage_idx: int = -1

            for stage_idx, cap in enumerate(validated_capabilities):
                executed_stage_idx = stage_idx
                current_ctx = context

                # Cancellation check before stage execution
                if current_ctx.cancellation_token is not None and current_ctx.cancellation_token.is_cancelled:
                    if self._darpana is not None:
                        from sarathi.darpana import MarutiRecord

                        self._darpana.record_maruti(
                            MarutiRecord(
                                run_id=current_ctx.run_id,
                                request_id=current_ctx.request_id,
                                trace_id=current_ctx.trace_id,
                                span_id=current_ctx.span_id,
                                phase_name="cancellation",
                                component="nabhi.pravaha",
                                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                duration_ns=0,
                                outcome="failure",
                                error_type="DoshError",
                                failure_code=FailureCode.EXECUTION_FAILED,
                                attributes={"reason": "cancelled_by_user", "cancelled": True},
                            )
                        )
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Execution was cancelled.",
                        context={"cancelled": True},
                    )

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

                # Smriti cache check
                cache_key = None
                cached_result = None
                if self._smriti is not None:
                    from sarathi.darpana import MarutiRecord

                    cache_key = compute_cache_key(
                        current_request,
                        cap.declaration.capability_id,
                        cap.declaration.version,
                        prior_result=prior_result,
                    )
                    t_start_ns = time.perf_counter_ns()
                    cached_result, cache_tier = self._smriti.get_with_tier(cache_key)
                    duration_ns = max(0, time.perf_counter_ns() - t_start_ns)

                    if self._darpana is not None:
                        cache_outcome = "hit" if cached_result is not None else "miss"
                        cache_attrs: dict[str, Any] = {
                            "capability_id": cap.declaration.capability_id,
                            "outcome": cache_outcome,
                        }
                        if cached_result is not None and cache_tier is not None:
                            cache_attrs["cache_tier"] = cache_tier

                        self._darpana.record_maruti(
                            MarutiRecord(
                                run_id=current_ctx.run_id,
                                request_id=current_ctx.request_id,
                                trace_id=current_ctx.trace_id,
                                span_id=current_ctx.span_id,
                                phase_name="cache.lookup",
                                component="smriti",
                                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                duration_ns=duration_ns,
                                outcome="success",
                                attributes=cache_attrs,
                            )
                        )

                if cached_result is not None:
                    prior_result = cached_result
                else:
                    try:
                        scope = (
                            self._darpana.time_scope(
                                context=current_ctx,
                                phase_name="pipeline_stage",
                                component="nabhi.pravaha",
                                attributes={
                                    "capability_id": cap.declaration.capability_id,
                                    "plugin_id": cap.declaration.plugin_id,
                                },
                            )
                            if self._darpana is not None
                            else nullcontext()
                        )
                        with scope:
                            prior_result = self._yantra.execute(
                                capability=cap,
                                request=current_request,
                                context=current_ctx,
                                prior_result=prior_result,
                            )

                        # Check cancellation immediately after Yantra execution before caching or continuation
                        if current_ctx.cancellation_token is not None and current_ctx.cancellation_token.is_cancelled:
                            current_ctx.cancellation_token.check_cancelled()

                        if self._smriti is not None and cache_key is not None:
                            try:
                                self._smriti.put(cache_key, prior_result)
                            except Exception:
                                # Auxiliary cache write failure must not fail successful capability execution
                                pass

                        self._record_pramana_if_available(cap, prior_result, current_ctx)

                    except DoshError as dosh_err:
                        is_cancelled = bool(dosh_err.context.get("cancelled")) or (
                            current_ctx.cancellation_token is not None and current_ctx.cancellation_token.is_cancelled
                        )
                        if is_cancelled:
                            raise dosh_err

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
                                with self._quarantine_transition_scope(
                                    context=current_ctx,
                                    capability_id=rec.capability_id,
                                    lifecycle_status=QuarantineStatus.TERMINAL.value,
                                    attempt_count=rec.attempt_count,
                                    max_retries=rec.max_retries,
                                ):
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
                        with self._quarantine_transition_scope(
                            context=current_ctx,
                            capability_id=init_rec.capability_id,
                            lifecycle_status=QuarantineStatus.QUARANTINED.value,
                            attempt_count=init_rec.attempt_count,
                            max_retries=init_rec.max_retries,
                        ):
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
                                if self._smriti is not None and cache_key is not None:
                                    try:
                                        self._smriti.put(cache_key, prior_result)
                                    except Exception:
                                        # Auxiliary cache write failure must not fail successful capability execution
                                        pass
                                break
                            except DoshError as retry_err:
                                last_err = retry_err
                                curr_rec = self._quarantine_store.get_record(curr_rec.quarantine_id) or curr_rec
                                if not self._retry_policy.is_retryable(last_err.code, curr_rec.attempt_count):
                                    raise retry_err

                if prior_result.next_requirement is not None:
                    break
                else:
                    completed_capability_ids.add(cap.declaration.capability_id)

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

            # Determine resumption stages
            current_cap_id = cap.declaration.capability_id
            resuming_stages = (
                (current_cap_id,) + current_plan.capability_ids[executed_stage_idx + 1 :]
                if prior_result.resume_self
                else current_plan.capability_ids[executed_stage_idx + 1 :]
            )

            # Resolve next plan for next_req_id through Manthan
            current_request = Request(
                request_id=current_request.request_id,
                requirement=next_req_id,
                inputs=current_request.inputs,
                profile=current_request.profile,
                custom_options=current_request.custom_options,
                output_root=current_request.output_root,
                preserve_partial=current_request.preserve_partial,
                cancellation_token=current_request.cancellation_token,
                metadata=current_request.metadata,
            )
            next_plan = self._manthan.resolve(current_request)

            # Filter out already completed prerequisites from next_plan
            unexecuted_next_stages = tuple(
                cid for cid in next_plan.capability_ids if cid not in completed_capability_ids
            )

            current_plan = CapabilityPlan(
                request_id=request.request_id,
                capability_ids=unexecuted_next_stages + resuming_stages,
            )

    def apply_lifecycle_action(
        self,
        action: LifecycleAction,
        *,
        request: Request | None = None,
        context: ExecutionContext | None = None,
    ) -> QuarantineRecord:
        """Apply a validated lifecycle transition (release, retry, terminate) to a quarantined item.

        Args:
            action: Typed LifecycleAction request.
            request: Optional Request override for retry re-execution.
            context: Optional ExecutionContext override for retry re-execution.

        Returns:
            The updated QuarantineRecord.

        Raises:
            TypeError: If action is not a LifecycleAction instance.
            DoshError(FailureCode.INVALID_CONFIGURATION): If no QuarantineStore is configured.
            DoshError(FailureCode.VALIDATION_FAILED): If transition is invalid, item ID is malformed,
                item does not exist, or required execution context is missing.
            DoshError(FailureCode.SECURITY_DENIED): If capability violates Kavacha security authorization.
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

        effective_req = request or action.request
        effective_ctx = context or action.context

        match action.action:
            case LifecycleActionType.RELEASE:
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
                scope = (
                    self._quarantine_transition_scope(
                        context=effective_ctx,
                        capability_id=existing.capability_id,
                        lifecycle_status=QuarantineStatus.RELEASED.value,
                        attempt_count=existing.attempt_count,
                        max_retries=existing.max_retries,
                    )
                    if effective_ctx is not None
                    else nullcontext()
                )
                with scope:
                    return self._quarantine_store.update_status(action.item_id, QuarantineStatus.RELEASED)

            case LifecycleActionType.TERMINATE:
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
                scope = (
                    self._quarantine_transition_scope(
                        context=effective_ctx,
                        capability_id=existing.capability_id,
                        lifecycle_status=QuarantineStatus.TERMINAL.value,
                        attempt_count=existing.attempt_count,
                        max_retries=existing.max_retries,
                    )
                    if effective_ctx is not None
                    else nullcontext()
                )
                with scope:
                    return self._quarantine_store.update_status(action.item_id, QuarantineStatus.TERMINAL)

            case LifecycleActionType.RETRY:
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

                if effective_req is None or effective_ctx is None:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message="Request and ExecutionContext are required to execute a retry through Yantra.",
                    )

                # Mandatory RETRY identity binding checks before ANY mutation or execution
                # 1. request.request_id == existing.request_id
                if effective_req.request_id != existing.request_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Request request_id '{effective_req.request_id}' does not match quarantined request_id '{existing.request_id}'.",
                    )

                # 2. context.request_id == existing.request_id
                if effective_ctx.request_id != existing.request_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Context request_id '{effective_ctx.request_id}' does not match quarantined request_id '{existing.request_id}'.",
                    )

                # 3. context.run_id == existing.run_id
                if effective_ctx.run_id != existing.run_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Context run_id '{effective_ctx.run_id}' does not match quarantined run_id '{existing.run_id}'.",
                    )

                # 4. context.trace_id == existing.trace_id
                if effective_ctx.trace_id != existing.trace_id:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Context trace_id '{effective_ctx.trace_id}' does not match quarantined trace_id '{existing.trace_id}'.",
                    )

                # 5. context.profile.value == existing.profile
                if effective_ctx.profile.value != existing.profile:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Context profile '{effective_ctx.profile.value}' does not match quarantined profile '{existing.profile}'.",
                    )

                # 6. Resolve target capability and verify registered declaration
                cap_id = existing.capability_id
                if cap_id not in self._capabilities:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Executable capability '{cap_id}' is not available in Pravaha capabilities.",
                    )
                cap = self._capabilities[cap_id]
                if not isinstance(cap, Capability):
                    raise TypeError(
                        f"Provided capability '{cap_id}' does not implement Capability protocol, "
                        f"got {type(cap).__name__}."
                    )

                registered_decl = self._registry.get_capability(cap_id)
                if registered_decl is None:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Quarantined capability '{cap_id}' is not registered in Kosh.",
                    )

                if cap.declaration != registered_decl:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Executable capability '{cap_id}' declaration does not match registered declaration in Kosh.",
                    )

                # 7. Recompute canonical input hash and verify match
                recomputed_hash = self._compute_input_hash(effective_req, cap, effective_ctx)
                if recomputed_hash != existing.input_hash:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message="Recomputed input hash does not match quarantined input hash.",
                    )

                # All checks passed: proceed with Yantra execution
                _, updated_rec = self._execute_retry_attempt(
                    cap=cap,
                    request=effective_req,
                    context=effective_ctx,
                    record=existing,
                )
                return updated_rec
