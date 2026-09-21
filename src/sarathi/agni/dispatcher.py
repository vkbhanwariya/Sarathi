"""Request execution pipeline, lifecycle boundary containment, and telemetry dispatching."""

from __future__ import annotations

import re
import time
import uuid
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sarathi.darpana import Darpana, record_maruti
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
from sarathi.nabhi import ArtifactBoundary, Manthan, Pravaha
from sarathi.sankalpa import ExecutionContext, Request, Result
from sarathi.sankalpa.cancellation import check_cancelled
from sarathi.shakti.darshana import identify_request
from sarathi.sutra import Settings


def record_terminal_summary(
    darpana: Darpana | None,
    settings: Settings,
    exec_ctx: ExecutionContext,
    request: Request,
    status: str,
    start_time_utc: str,
    duration_ms: int,
    artifact_count: int,
    warning_count: int,
    output_dir: str | None = None,
) -> None:
    """Safely record a sanitized TerminalRunSummary to Darpana without masking execution errors."""
    if darpana is None or not settings.telemetry_history_enabled:
        return

    try:
        from sarathi.darpana import TerminalRunSummary

        raw_req = request.request_id if request and request.request_id else exec_ctx.run_id
        safe_req = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_req) or exec_ctx.run_id

        summary = TerminalRunSummary(
            run_id=exec_ctx.run_id,
            request_id=safe_req,
            requirement=request.requirement,
            profile=request.profile.value,
            status=status,
            start_time_utc=start_time_utc,
            completed_at_utc=datetime.now(UTC).isoformat(),
            duration_ms=duration_ms,
            artifact_count=artifact_count,
            warning_count=warning_count,
            has_masked_identity=False,
            output_dir=output_dir,
        )
        darpana.record_run_summary(summary)
    except Exception:
        try:
            from sarathi.darpana import MarutiRecord

            darpana.record_maruti(
                MarutiRecord(
                    run_id=exec_ctx.run_id,
                    request_id=exec_ctx.request_id,
                    trace_id=exec_ctx.trace_id,
                    span_id=exec_ctx.span_id,
                    phase_name="telemetry.history_persistence_failure",
                    component="agni",
                    timestamp_utc=datetime.now(UTC).isoformat(),
                    duration_ns=0,
                    outcome="failure",
                    attributes={"error": "history_recording_failed"},
                )
            )
        except Exception:
            pass


def _prepare_execution_context(request: Request, context: ExecutionContext | None) -> ExecutionContext:
    """Reconcile request and supplied-context cancellation tokens."""
    effective_token = request.cancellation_token
    if context is not None:
        if context.cancellation_token is not None and request.cancellation_token is not None:
            if context.cancellation_token is not request.cancellation_token:
                raise DoshError(
                    code=FailureCode.VALIDATION_FAILED,
                    message="Conflicting distinct cancellation tokens provided in request and context.",
                )
        elif context.cancellation_token is not None and request.cancellation_token is None:
            effective_token = context.cancellation_token

        return (
            replace(context, cancellation_token=effective_token)
            if context.cancellation_token is not effective_token
            else context
        )

    return ExecutionContext(
        run_id=f"run-{uuid.uuid4().hex[:12]}",
        request_id=request.request_id,
        trace_id=f"tr-{uuid.uuid4().hex[:16]}",
        span_id=f"sp-{uuid.uuid4().hex[:8]}",
        profile=request.profile,
        cancellation_token=effective_token,
    )


def _commit_and_finalize_workspace(
    workspace: Any,
    raw_result: Result,
    request: Request,
    exec_ctx: ExecutionContext,
    effective_output_root: Path,
    darpana: Darpana | None,
    settings: Settings,
    t_start_utc: str,
    t_start_ns: int,
) -> Result:
    """Commit declared artifacts, finalize workspace, record terminal summary and return Result."""
    check_cancelled(exec_ctx)

    if raw_result.artifact_payloads:
        for payload in raw_result.artifact_payloads:
            check_cancelled(exec_ctx)
            workspace.commit_artifact(payload.intent, payload.content)

    check_cancelled(exec_ctx)

    manifest_metadata: dict[str, Any] = {
        "total_inputs": len(request.inputs),
        "input_ids": [inp.input_id for inp in request.inputs],
    }
    if "input_outcomes" in raw_result.metadata:
        manifest_metadata["input_outcomes"] = dict(raw_result.metadata["input_outcomes"])
    if "contributing_input_ids" in raw_result.metadata:
        manifest_metadata["contributing_input_ids"] = list(raw_result.metadata["contributing_input_ids"])

    workspace.finalize(
        success=True,
        provenance=raw_result.provenance,
        warnings=raw_result.warnings,
        metadata=manifest_metadata,
    )

    duration_ms = max(0, (time.perf_counter_ns() - t_start_ns) // 1_000_000)
    try:
        resolved_out = workspace.output_dir.resolve()
        resolved_root = effective_output_root.resolve()
        out_dir_ref = str(resolved_out.relative_to(resolved_root)).replace("\\", "/") if workspace.output_dir else None
    except (ValueError, OSError):
        out_dir_ref = str(workspace.output_dir).replace("\\", "/") if workspace.output_dir else None

    record_terminal_summary(
        darpana=darpana,
        settings=settings,
        exec_ctx=exec_ctx,
        request=request,
        status="completed",
        start_time_utc=t_start_utc,
        duration_ms=duration_ms,
        artifact_count=len(workspace.committed_artifacts),
        warning_count=len(raw_result.warnings),
        output_dir=out_dir_ref,
    )

    result_metadata = dict(raw_result.metadata)
    result_metadata["run_id"] = exec_ctx.run_id
    result_metadata["request_id"] = request.request_id
    if workspace.output_dir:
        result_metadata["output_dir"] = str(workspace.output_dir.resolve())

    return Result(
        data=raw_result.data,
        artifact_payloads=(),
        artifacts=workspace.committed_artifacts,
        confidence=raw_result.confidence,
        warnings=raw_result.warnings,
        provenance=raw_result.provenance,
        next_requirement=raw_result.next_requirement,
        metadata=result_metadata,
    )


def _handle_execution_failure(
    proc_exc: Exception,
    workspace: Any,
    request: Request,
    exec_ctx: ExecutionContext,
    effective_output_root: Path,
    darpana: Darpana | None,
    settings: Settings,
    t_start_utc: str,
    t_start_ns: int,
) -> None:
    """Handle cleanup, cancellation reporting, and failure summary recording upon error."""
    duration_ms = max(0, (time.perf_counter_ns() - t_start_ns) // 1_000_000)
    is_cancelled = (isinstance(proc_exc, DoshError) and bool(proc_exc.context.get("cancelled"))) or (
        exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled
    )
    term_status = "cancelled" if is_cancelled else "failed"

    if is_cancelled and darpana is not None:
        record_maruti(
            darpana=darpana,
            context=exec_ctx,
            phase_name="cancellation",
            component="agni",
            duration_ns=0,
            outcome="cancelled",
            attributes={"cancelled": True},
        )

    if not workspace.is_finalized:
        try:
            workspace.finalize(
                success=False,
                status=term_status,
            )
        except (OSError, DoshError) as cleanup_exc:
            if darpana is not None:
                record_maruti(
                    darpana=darpana,
                    context=exec_ctx,
                    phase_name="workspace.finalize_cleanup_failure",
                    component="agni",
                    duration_ns=0,
                    outcome="failure",
                    attributes={"error_type": type(cleanup_exc).__name__},
                )

        out_dir_fail = None
        try:
            out_dir_fail = str(workspace.output_dir.relative_to(effective_output_root)).replace("\\", "/")
        except Exception:
            pass

        try:
            record_terminal_summary(
                darpana=darpana,
                settings=settings,
                exec_ctx=exec_ctx,
                request=request,
                status=term_status,
                start_time_utc=t_start_utc,
                duration_ms=duration_ms,
                artifact_count=len(getattr(workspace, "committed_artifacts", ())),
                warning_count=0,
                output_dir=out_dir_fail,
            )
        except Exception:
            pass


def execute_request(
    request: Request,
    context: ExecutionContext | None,
    artifact_boundary: ArtifactBoundary,
    output_root: Path,
    runtime_root: Path,
    kavacha: Kavacha,
    darpana: Darpana | None,
    manthan: Manthan,
    pravaha: Pravaha,
    settings: Settings,
) -> Result:
    """Execute a canonical Request through the full Agni-wired runtime path."""
    if not isinstance(request, Request):
        raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")

    if context is not None and not isinstance(context, ExecutionContext):
        raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

    # 1. Prevent re-ingestion from active staging/runtime or effective output roots via Kavacha
    effective_output_root = (request.output_root or output_root).resolve()
    kavacha.validate_source_destination_overlap(
        request.inputs,
        (runtime_root, effective_output_root),
    )

    t_start_utc = datetime.now(UTC).isoformat()
    t_start_ns = time.perf_counter_ns()

    # 2. Reconcile request and supplied-context cancellation tokens
    exec_ctx = _prepare_execution_context(request, context)

    # 3. Open RunWorkspace on the canonical ArtifactBoundary for this validated run
    with artifact_boundary.begin_run(
        run_id=exec_ctx.run_id,
        requirement=request.requirement,
        output_root=effective_output_root,
        preserve_partial=request.preserve_partial,
        input_sources=request.inputs,
        context=exec_ctx,
    ) as workspace:
        try:
            check_cancelled(exec_ctx)

            # Pre-Manthan Darshana Identification (Timed in Darpana)
            id_scope = (
                darpana.time_scope(
                    context=exec_ctx,
                    phase_name="identification",
                    component="shakti.darshana",
                    attributes={"input_count": len(request.inputs)},
                )
                if darpana is not None
                else nullcontext()
            )
            with id_scope:
                identified_request = identify_request(request)

            check_cancelled(exec_ctx)

            # Manthan Capability Plan Resolution (Timed in Darpana)
            res_scope = (
                darpana.time_scope(
                    context=exec_ctx,
                    phase_name="resolution",
                    component="nabhi.manthan",
                    attributes={"requirement": identified_request.requirement},
                )
                if darpana is not None
                else nullcontext()
            )
            with res_scope:
                plan = manthan.resolve(identified_request)

            # 4. Pravaha Dynamic Pipeline Execution (includes Kavacha security authorization)
            raw_result = pravaha.execute(plan, identified_request, exec_ctx)

            return _commit_and_finalize_workspace(
                workspace=workspace,
                raw_result=raw_result,
                request=request,
                exec_ctx=exec_ctx,
                effective_output_root=effective_output_root,
                darpana=darpana,
                settings=settings,
                t_start_utc=t_start_utc,
                t_start_ns=t_start_ns,
            )
        except Exception as proc_exc:
            _handle_execution_failure(
                proc_exc=proc_exc,
                workspace=workspace,
                request=request,
                exec_ctx=exec_ctx,
                effective_output_root=effective_output_root,
                darpana=darpana,
                settings=settings,
                t_start_utc=t_start_utc,
                t_start_ns=t_start_ns,
            )
            raise
