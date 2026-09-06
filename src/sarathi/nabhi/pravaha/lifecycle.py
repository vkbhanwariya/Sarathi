"""Quarantine lifecycle state transitions, operator actions, and retry attempt execution."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.pravaha.common import (
    _SAFE_ID_PATTERN,
    authorize_capability,
    compute_input_hash,
    quarantine_transition_scope,
    record_pramana_if_available,
)
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

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.kavacha import Kavacha


def execute_retry_attempt(
    cap: Capability,
    request: Request,
    context: ExecutionContext,
    record: QuarantineRecord,
    prior_result: Result | None,
    quarantine_store: QuarantineStore | None,
    retry_policy: RetryPolicy,
    yantra: Yantra,
    darpana: Darpana | None,
    kavacha: Kavacha | None,
    registry: Kosh,
) -> tuple[Result | None, QuarantineRecord]:
    """Execute one retry attempt through Yantra with full failure lifecycle handling."""
    if quarantine_store is None:
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
    authorize_capability(kavacha, registry, cap)

    # Check cancellation before retry execution; cancellation bypasses retry
    if request.cancellation_token is not None and request.cancellation_token.is_cancelled:
        raise DoshError(
            code=FailureCode.OPERATION_CANCELLED,
            message="Execution was cancelled before retry attempt.",
            context={"cancelled": True},
        )
    if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
        raise DoshError(
            code=FailureCode.OPERATION_CANCELLED,
            message="Execution was cancelled before retry attempt.",
            context={"cancelled": True},
        )

    new_attempt = record.attempt_count + 1

    # Mark attempt as actively being retried in store with measured lifecycle time_scope
    with quarantine_transition_scope(
        darpana=darpana,
        context=context,
        capability_id=record.capability_id,
        lifecycle_status=QuarantineStatus.RETRIED.value,
        attempt_count=new_attempt,
        max_retries=record.max_retries,
    ):
        retried_rec = quarantine_store.update_status(
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
        darpana.time_scope(
            context=retry_ctx,
            phase_name="retry_attempt",
            component="nabhi.pravaha",
            attributes={
                "capability_id": cap.declaration.capability_id,
                "attempt": new_attempt,
                "max_retries": record.max_retries,
            },
        )
        if darpana is not None
        else nullcontext()
    )

    try:
        with scope:
            result = yantra.execute(
                capability=cap,
                request=request,
                context=retry_ctx,
                prior_result=prior_result,
            )

        # Retry succeeded: release quarantined status with measured lifecycle time_scope
        with quarantine_transition_scope(
            darpana=darpana,
            context=retry_ctx,
            capability_id=record.capability_id,
            lifecycle_status=QuarantineStatus.RELEASED.value,
            attempt_count=new_attempt,
            max_retries=record.max_retries,
        ):
            released_rec = quarantine_store.update_status(
                record.quarantine_id,
                QuarantineStatus.RELEASED,
                attempt_count=new_attempt,
            )
        record_pramana_if_available(darpana, cap, result, retry_ctx)
        return result, released_rec
    except DoshError as dosh_err:
        # Check if this failure remains retryable and retries are not exhausted
        is_still_retryable = retry_policy.is_retryable(dosh_err.code, new_attempt)
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
            with quarantine_transition_scope(
                darpana=darpana,
                context=retry_ctx,
                capability_id=updated_rec.capability_id,
                lifecycle_status=QuarantineStatus.TERMINAL.value,
                attempt_count=updated_rec.attempt_count,
                max_retries=updated_rec.max_retries,
            ):
                quarantine_store.quarantine(updated_rec)
        else:
            quarantine_store.quarantine(updated_rec)
        raise dosh_err


def apply_lifecycle_action(
    action: LifecycleAction,
    request: Request | None,
    context: ExecutionContext | None,
    quarantine_store: QuarantineStore | None,
    retry_policy: RetryPolicy,
    yantra: Yantra,
    darpana: Darpana | None,
    kavacha: Kavacha | None,
    registry: Kosh,
    capabilities: Mapping[str, Capability],
) -> QuarantineRecord:
    """Apply a validated lifecycle transition (release, retry, terminate) to a quarantined item."""
    if not isinstance(action, LifecycleAction):
        raise TypeError(f"action must be a LifecycleAction instance, got {type(action).__name__}.")

    if quarantine_store is None:
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

    existing = quarantine_store.get_record(action.item_id)
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
                quarantine_transition_scope(
                    darpana=darpana,
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
                return quarantine_store.update_status(action.item_id, QuarantineStatus.RELEASED)

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
                quarantine_transition_scope(
                    darpana=darpana,
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
                return quarantine_store.update_status(action.item_id, QuarantineStatus.TERMINAL)

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
            if effective_req.request_id != existing.request_id:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Request request_id '{effective_req.request_id}' does not match quarantined request_id '{existing.request_id}'.",
                )

            if effective_ctx.request_id != existing.request_id:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Context request_id '{effective_ctx.request_id}' does not match quarantined request_id '{existing.request_id}'.",
                )

            if effective_ctx.run_id != existing.run_id:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Context run_id '{effective_ctx.run_id}' does not match quarantined run_id '{existing.run_id}'.",
                )

            if effective_ctx.trace_id != existing.trace_id:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Context trace_id '{effective_ctx.trace_id}' does not match quarantined trace_id '{existing.trace_id}'.",
                )

            if effective_ctx.profile.value != existing.profile:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message=f"Context profile '{effective_ctx.profile.value}' does not match quarantined profile '{existing.profile}'.",
                )

            # Resolve target capability and verify registered declaration
            cap_id = existing.capability_id
            if cap_id not in capabilities:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message=f"Executable capability '{cap_id}' is not available in Pravaha capabilities.",
                )
            cap = capabilities[cap_id]
            if not isinstance(cap, Capability):
                raise TypeError(
                    f"Provided capability '{cap_id}' does not implement Capability protocol, "
                    f"got {type(cap).__name__}."
                )

            registered_decl = registry.get_capability(cap_id)
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

            # Recompute canonical input hash and verify match
            recomputed_hash = compute_input_hash(effective_req, cap, effective_ctx)
            if recomputed_hash != existing.input_hash:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="Recomputed input hash does not match quarantined input hash.",
                )

            # All checks passed: proceed with Yantra execution
            _, updated_rec = execute_retry_attempt(
                cap=cap,
                request=effective_req,
                context=effective_ctx,
                record=existing,
                prior_result=None,
                quarantine_store=quarantine_store,
                retry_policy=retry_policy,
                yantra=yantra,
                darpana=darpana,
                kavacha=kavacha,
                registry=registry,
            )
            return updated_rec
