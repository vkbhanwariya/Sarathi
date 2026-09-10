"""Core dynamic pipeline plan execution loop, continuation hand-off, and cache coordination."""

from __future__ import annotations

import time
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.manthan import CapabilityPlan, Manthan
from sarathi.nabhi.pravaha.common import (
    authorize_capability,
    compute_input_hash,
    quarantine_transition_scope,
    record_pramana_if_available,
)
from sarathi.nabhi.pravaha.lifecycle import execute_retry_attempt
from sarathi.nabhi.quarantine import (
    QuarantineRecord,
    QuarantineStatus,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import (
    Capability,
    ExecutionContext,
    Request,
    Result,
    WarningRecord,
)
from sarathi.smriti import SmritiCache, compute_cache_key
from sarathi.yantra import Yantra

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.kavacha import Kavacha


def execute_pipeline(
    plan: CapabilityPlan,
    request: Request,
    context: ExecutionContext,
    manthan: Manthan,
    registry: Kosh,
    yantra: Yantra,
    capabilities: Mapping[str, Capability],
    quarantine_store: QuarantineStore | None,
    retry_policy: RetryPolicy,
    darpana: Darpana | None,
    kavacha: Kavacha | None,
    smriti: SmritiCache | None,
) -> Result:
    """Execute a resolved capability plan across configured capabilities through Yantra."""
    # Validate argument types
    if not isinstance(plan, CapabilityPlan):
        raise TypeError(f"plan must be a CapabilityPlan instance, got {type(plan).__name__}.")
    if not isinstance(request, Request):
        raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
    if not isinstance(context, ExecutionContext):
        raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

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
    accumulated_warnings: list[WarningRecord] = []

    def _sync_warnings(res: Result | None) -> Result | None:
        if res is None:
            return None
        for w in res.warnings:
            if w not in accumulated_warnings:
                accumulated_warnings.append(w)
        if res.warnings != tuple(accumulated_warnings):
            return replace(res, warnings=tuple(accumulated_warnings))
        return res

    while True:
        # Pre-execution validation: validate all planned capabilities against Kosh and executable bindings
        validated_capabilities: list[Capability] = []
        for cap_id in current_plan.capability_ids:
            registered_decl = registry.get_capability(cap_id)
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

            # Authorize against Kavacha before execution
            authorize_capability(kavacha, registry, executable_cap)
            validated_capabilities.append(executable_cap)

        # Execute pipeline in plan order through Yantra with failure lifecycle handling
        executed_stage_idx: int = -1

        for stage_idx, cap in enumerate(validated_capabilities):
            executed_stage_idx = stage_idx
            current_ctx = context

            # Cancellation check before stage execution
            if current_ctx.cancellation_token is not None and current_ctx.cancellation_token.is_cancelled:
                if darpana is not None:
                    from sarathi.darpana import MarutiRecord

                    darpana.record_maruti(
                        MarutiRecord(
                            run_id=current_ctx.run_id,
                            request_id=current_ctx.request_id,
                            trace_id=current_ctx.trace_id,
                            span_id=current_ctx.span_id,
                            phase_name="cancellation",
                            component="nabhi.pravaha",
                            timestamp_utc=datetime.now(timezone.utc).isoformat(),
                            duration_ns=0,
                            outcome="cancelled",
                            error_type="DoshError",
                            failure_code=FailureCode.OPERATION_CANCELLED,
                            attributes={"reason": "cancelled_by_user", "cancelled": True},
                        )
                    )
                raise DoshError(
                    code=FailureCode.OPERATION_CANCELLED,
                    message="Execution was cancelled.",
                    context={"cancelled": True},
                )

            input_hash = compute_input_hash(current_request, cap, current_ctx)
            quar_id = f"quar-{input_hash[:16]}"

            # Check if attempt is already terminal in quarantine
            if quarantine_store is not None:
                existing_rec = quarantine_store.get_record(quar_id)
                if existing_rec is not None and existing_rec.status == QuarantineStatus.TERMINAL:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=f"Attempt for capability '{cap.declaration.capability_id}' is in terminal quarantine state and cannot be executed again.",
                    )

            # Smriti cache check
            cache_key = None
            cached_result = None
            if smriti is not None:
                from sarathi.darpana import MarutiRecord

                cap_asset_ver = str(
                    getattr(cap, "asset_version", "")
                    or getattr(cap.declaration, "asset_version", "")
                    or (cap.declaration.metadata.get("asset_version", "") if cap.declaration.metadata else "")
                    or ""
                )
                cache_key = compute_cache_key(
                    current_request,
                    cap.declaration.capability_id,
                    cap.declaration.version,
                    prior_result=prior_result,
                    asset_version=cap_asset_ver,
                )
                t_start_ns = time.perf_counter_ns()
                cached_result, cache_tier = smriti.get_with_tier(cache_key)
                duration_ns = max(0, time.perf_counter_ns() - t_start_ns)

                if darpana is not None:
                    cache_outcome = "hit" if cached_result is not None else "miss"
                    cache_attrs: dict[str, Any] = {
                        "capability_id": cap.declaration.capability_id,
                        "outcome": cache_outcome,
                    }
                    if cached_result is not None and cache_tier is not None:
                        cache_attrs["cache_tier"] = cache_tier

                    darpana.record_maruti(
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
                prior_result = _sync_warnings(cached_result)
            else:
                try:
                    scope = (
                        darpana.time_scope(
                            context=current_ctx,
                            phase_name="pipeline_stage",
                            component="nabhi.pravaha",
                            attributes={
                                "capability_id": cap.declaration.capability_id,
                                "plugin_id": cap.declaration.plugin_id,
                            },
                        )
                        if darpana is not None
                        else nullcontext()
                    )
                    with scope:
                        prior_result = _sync_warnings(
                            yantra.execute(
                                capability=cap,
                                request=current_request,
                                context=current_ctx,
                                prior_result=prior_result,
                            )
                        )

                    # Check cancellation immediately after Yantra execution before caching or continuation
                    if current_ctx.cancellation_token is not None and current_ctx.cancellation_token.is_cancelled:
                        current_ctx.cancellation_token.check_cancelled()

                    if smriti is not None and cache_key is not None:
                        try:
                            smriti.put(cache_key, prior_result)
                        except Exception as cache_err:
                            if darpana is not None:
                                from sarathi.darpana import MarutiRecord

                                darpana.record_maruti(
                                    MarutiRecord(
                                        run_id=current_ctx.run_id,
                                        request_id=current_ctx.request_id,
                                        trace_id=current_ctx.trace_id,
                                        span_id=current_ctx.span_id,
                                        phase_name="cache.write_failure",
                                        component="smriti",
                                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                        duration_ns=0,
                                        outcome="failure",
                                        attributes={"error_type": type(cache_err).__name__},
                                    )
                                )

                    record_pramana_if_available(darpana, cap, prior_result, current_ctx)

                except DoshError as dosh_err:
                    is_cancelled = (
                        dosh_err.code == FailureCode.OPERATION_CANCELLED
                        or bool(dosh_err.context.get("cancelled"))
                        or (
                            current_ctx.cancellation_token is not None
                            and current_ctx.cancellation_token.is_cancelled
                        )
                    )
                    if is_cancelled:
                        raise dosh_err

                    current_attempt = 0
                    is_retry_allowed = retry_policy.is_retryable(dosh_err.code, current_attempt)

                    if not is_retry_allowed:
                        # Non-retryable or zero-retries policy: mark terminal quarantine if store configured
                        if quarantine_store is not None:
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
                                max_retries=retry_policy.max_retries,
                                status=QuarantineStatus.TERMINAL,
                                created_at_utc=datetime.now(timezone.utc).isoformat(),
                                updated_at_utc=datetime.now(timezone.utc).isoformat(),
                            )
                            with quarantine_transition_scope(
                                darpana=darpana,
                                context=current_ctx,
                                capability_id=rec.capability_id,
                                lifecycle_status=QuarantineStatus.TERMINAL.value,
                                attempt_count=rec.attempt_count,
                                max_retries=rec.max_retries,
                            ):
                                quarantine_store.quarantine(rec)
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
                        max_retries=retry_policy.max_retries,
                        status=QuarantineStatus.QUARANTINED,
                        created_at_utc=datetime.now(timezone.utc).isoformat(),
                        updated_at_utc=datetime.now(timezone.utc).isoformat(),
                    )
                    if quarantine_store is None:
                        raise DoshError(
                            code=FailureCode.INVALID_CONFIGURATION,
                            message="Quarantine store is unconfigured during quarantine transition.",
                        )
                    with quarantine_transition_scope(
                        darpana=darpana,
                        context=current_ctx,
                        capability_id=init_rec.capability_id,
                        lifecycle_status=QuarantineStatus.QUARANTINED.value,
                        attempt_count=init_rec.attempt_count,
                        max_retries=init_rec.max_retries,
                    ):
                        quarantine_store.quarantine(init_rec)

                    curr_rec = init_rec
                    last_err: DoshError = dosh_err
                    while retry_policy.is_retryable(last_err.code, curr_rec.attempt_count):
                        try:
                            retry_res, updated_rec = execute_retry_attempt(
                                cap=cap,
                                request=current_request,
                                context=current_ctx,
                                record=curr_rec,
                                prior_result=prior_result,
                                quarantine_store=quarantine_store,
                                retry_policy=retry_policy,
                                yantra=yantra,
                                darpana=darpana,
                                kavacha=kavacha,
                                registry=registry,
                            )
                            prior_result = _sync_warnings(retry_res)
                            if smriti is not None and cache_key is not None:
                                try:
                                    smriti.put(cache_key, prior_result)
                                except Exception as cache_err:
                                    if darpana is not None:
                                        from sarathi.darpana import MarutiRecord

                                        darpana.record_maruti(
                                            MarutiRecord(
                                                run_id=current_ctx.run_id,
                                                request_id=current_ctx.request_id,
                                                trace_id=current_ctx.trace_id,
                                                span_id=current_ctx.span_id,
                                                phase_name="cache.write_failure",
                                                component="smriti",
                                                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                                duration_ns=0,
                                                outcome="failure",
                                                attributes={"error_type": type(cache_err).__name__},
                                            )
                                        )
                            break
                        except DoshError as retry_err:
                            is_cancelled = (
                                retry_err.code == FailureCode.OPERATION_CANCELLED
                                or bool(retry_err.context.get("cancelled"))
                                or (
                                    current_ctx.cancellation_token is not None
                                    and current_ctx.cancellation_token.is_cancelled
                                )
                            )
                            if is_cancelled:
                                raise retry_err
                            last_err = retry_err
                            curr_rec = quarantine_store.get_record(curr_rec.quarantine_id) or curr_rec
                            if not retry_policy.is_retryable(last_err.code, curr_rec.attempt_count):
                                raise retry_err

            if prior_result.next_requirement is not None:
                break
            else:
                completed_capability_ids.add(cap.declaration.capability_id)

        if prior_result is None:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Capability execution yielded no result from plan.",
            )

        # Normal final result
        if prior_result.next_requirement is None:
            return _sync_warnings(prior_result)

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        next_req_id = prior_result.next_requirement
        if next_req_id in seen_requirements:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message=f"Repeated requirement '{next_req_id}' in pipeline execution is rejected.",
            )
        seen_requirements.add(next_req_id)

        current_cap_id = cap.declaration.capability_id
        remaining_stages = (
            (current_cap_id,) + current_plan.capability_ids[executed_stage_idx + 1 :]
            if prior_result.resume_self
            else current_plan.capability_ids[executed_stage_idx + 1 :]
        )

        current_request, current_plan = manthan.resolve_continuation(
            current_request,
            next_req_id,
            completed_capability_ids=completed_capability_ids,
            remaining_capability_ids=remaining_stages,
        )
