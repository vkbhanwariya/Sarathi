"""Agni - Runtime Bootstrap and Composition Root for Sarathi V2.

Composes configuration, global shared services, core kernel components, plugin discovery/registration,
lifecycle management, and canonical request execution. Wires owners together; does not absorb their logic.
"""

from __future__ import annotations

import re
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.kavacha import Kavacha
from sarathi.nabhi import (
    ArtifactBoundary,
    Dvara,
    Kosh,
    Manthan,
    Prana,
    Pravaha,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    ExecutionContext,
    PluginInfo,
    Request,
    Result,
)
from sarathi.shakti.bank_statements import BankStatementCapability
from sarathi.shakti.darshana import DarshanaCapability, identify_request
from sarathi.shakti.font_conversion import FontConversionCapability
from sarathi.shakti.native_extraction import NativeExtractionCapability
from sarathi.shakti.ocr import OCRCapability
from sarathi.shakti.translation import TranslationCapability
from sarathi.smriti import SmritiCache
from sarathi.sutra import Settings, load_settings
from sarathi.yantra import DeviceInventory, Yantra


class Agni:
    """Composition root for Sarathi V2 runtime services and execution lifecycle."""

    def __init__(
        self,
        settings: Settings | Path | str | None = None,
        *,
        runtime_root: Path | str | None = None,
        output_root: Path | str | None = None,
        input_root: Path | str | None = None,
        capabilities: Mapping[str, Capability] | None = None,
        plugins: Sequence[PluginInfo] | None = None,
        inventory: DeviceInventory | None = None,
        darpana: Darpana | None = None,
        kavacha: Kavacha | None = None,
        smriti: SmritiCache | None = None,
        context: ExecutionContext | None = None,
    ) -> None:
        """Initialize Agni composition root and construct global services in dependency order.

        Preflights and validates all explicit constructor arguments and consumed settings
        before performing any directory creation or observable registry mutations.

        Args:
            settings: Optional Settings instance, or path to TOML configuration.
            runtime_root: Optional runtime staging directory override.
            output_root: Optional output directory override.
            input_root: Optional input directory override.
            capabilities: Optional capability mapping override (useful for testing).
            inventory: Optional DeviceInventory override for Yantra.
            darpana: Optional Darpana telemetry service instance.
            kavacha: Optional Kavacha security service instance.
            context: Optional bootstrap ExecutionContext.

        Raises:
            TypeError: On invalid argument types.
            DoshError: On configuration, security policy, or storage initialization validation failures.
        """
        # --- Preflight Phase: Strict argument and type validation BEFORE any side effects ---

        # 1. Validate Context
        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        bootstrap_ctx = context or ExecutionContext(
            run_id="bootstrap",
            request_id="bootstrap",
            trace_id="bootstrap",
            span_id="bootstrap-001",
        )

        # 1. Validate Settings
        active_settings: Settings
        match settings:
            case None:
                active_settings = Settings()
            case Settings():
                active_settings = settings
            case Path() | str():
                active_settings = load_settings(settings, darpana=darpana, context=bootstrap_ctx)
            case _:
                raise TypeError(f"settings must be Settings, Path, str, or None, got {type(settings).__name__}.")

        # 2. Validate & Resolve Storage Roots (Sutra-owned defaults)
        def _resolve_root(arg_val: Path | str | None, setting_val: Path, param_name: str) -> Path:
            if arg_val is not None:
                if not isinstance(arg_val, (Path, str)):
                    raise TypeError(f"{param_name} must be a Path, str, or None, got {type(arg_val).__name__}.")
                if not str(arg_val).strip():
                    raise DoshError(
                        code=FailureCode.INVALID_CONFIGURATION,
                        message=f"{param_name} cannot be empty.",
                    )
                return Path(arg_val).resolve()
            return setting_val.resolve()

        validated_runtime_root = _resolve_root(runtime_root, active_settings.storage_runtime_root, "runtime_root")
        validated_output_root = _resolve_root(output_root, active_settings.storage_output_root, "output_root")
        validated_input_root = _resolve_root(input_root, active_settings.storage_input_root, "input_root")

        # 3. Validate Darpana (History storage strictly bounded under Runtime/Telemetry)
        if darpana is not None and not isinstance(darpana, Darpana):
            raise TypeError(f"darpana must be a Darpana instance or None, got {type(darpana).__name__}.")
        hist_dir = (validated_runtime_root / "Telemetry").resolve()
        if active_settings.telemetry_history_enabled:
            if active_settings.telemetry_history_path is not None:
                user_hist = Path(active_settings.telemetry_history_path)
                if user_hist.is_absolute():
                    raise DoshError(
                        code=FailureCode.INVALID_CONFIGURATION,
                        message="telemetry.history_path cannot be an absolute path; it must be relative to Runtime/Telemetry.",
                    )
                resolved_hist = (hist_dir / user_hist).resolve()
                if not (resolved_hist == hist_dir or hist_dir in resolved_hist.parents):
                    raise DoshError(
                        code=FailureCode.INVALID_CONFIGURATION,
                        message="telemetry.history_path escapes the Runtime/Telemetry directory.",
                    )
                hist_path = resolved_hist
            else:
                hist_path = hist_dir / (
                    "history.db" if active_settings.telemetry_history_format == "sqlite" else "history.jsonl"
                )
        else:
            hist_path = None
        active_darpana = darpana or Darpana(
            capacity=1000,
            history_path=hist_path,
            history_format=active_settings.telemetry_history_format,
            history_max_records=active_settings.telemetry_history_max_records,
        )

        # 4. Validate Kavacha & Security Policy
        active_kavacha: Kavacha
        if kavacha is not None:
            if not isinstance(kavacha, Kavacha):
                raise TypeError(f"kavacha must be a Kavacha instance or None, got {type(kavacha).__name__}.")
            active_kavacha = kavacha
        else:
            active_kavacha = Kavacha(active_settings.security_policy())

        # Canonical root overlap validation using Kavacha
        active_kavacha.validate_source_destination_overlap(
            [validated_input_root],
            (validated_runtime_root, validated_output_root),
        )
        active_kavacha.validate_source_destination_overlap(
            [validated_runtime_root],
            validated_output_root,
        )

        # 6. Validate Capabilities Mapping
        active_capabilities: dict[str, Capability]
        if capabilities is not None:
            if not isinstance(capabilities, Mapping):
                raise TypeError(f"capabilities must be a Mapping or None, got {type(capabilities).__name__}.")
            for cap_k, cap_v in capabilities.items():
                if not isinstance(cap_k, str) or not cap_k.strip():
                    raise TypeError("Capability mapping keys must be non-empty strings.")
                if not isinstance(cap_v, Capability):
                    raise TypeError(f"Capability '{cap_k}' does not implement Capability protocol.")
            active_capabilities = dict(capabilities)
        else:
            active_capabilities = {
                "identify": DarshanaCapability(),
                "read_native": NativeExtractionCapability(),
                "ocr": OCRCapability(),
                "bank_statements": BankStatementCapability(darpana=active_darpana),
                "font_conversion": FontConversionCapability(darpana=active_darpana),
                "translation": TranslationCapability(darpana=active_darpana),
            }

        # 7. Validate Inventory - use factual default inventory
        active_inventory: DeviceInventory
        if inventory is not None:
            if not isinstance(inventory, DeviceInventory):
                raise TypeError(
                    f"inventory must be a DeviceInventory instance or None, got {type(inventory).__name__}."
                )
            active_inventory = inventory
        else:
            active_inventory = Yantra.default_inventory()

        # 8. Validate Retry Policy
        active_retry_policy: RetryPolicy = RetryPolicy(
            max_retries=active_settings.pipeline_max_retries,
        )

        # --- Composition Phase: All checks passed, construct services in dependency order ---

        self._settings: Settings = active_settings
        self._darpana: Darpana = active_darpana
        self._runtime_root: Path = validated_runtime_root
        self._output_root: Path = validated_output_root
        self._input_root: Path = validated_input_root
        self._kavacha: Kavacha = active_kavacha
        self._capabilities: dict[str, Capability] = active_capabilities
        self._inventory: DeviceInventory = active_inventory
        self._retry_policy: RetryPolicy = active_retry_policy

        # Artifact Boundary
        self._artifact_boundary: ArtifactBoundary = ArtifactBoundary(
            runtime_root=self._runtime_root,
            output_root=self._output_root,
            kavacha=self._kavacha,
            darpana=self._darpana,
        )

        # Kosh & Dvara
        self._kosh: Kosh = Kosh()
        self._dvara: Dvara = Dvara(registry=self._kosh, darpana=self._darpana)
        self._dvara.register_builtins(context=bootstrap_ctx)

        # Register explicit plugins if supplied
        if plugins is not None:
            if not isinstance(plugins, (list, tuple)):
                raise TypeError(f"plugins must be a sequence of PluginInfo or None, got {type(plugins).__name__}.")
            for p in plugins:
                if not isinstance(p, PluginInfo):
                    raise TypeError(f"All items in plugins must be PluginInfo instances, got {type(p).__name__}.")
                if not self._kosh.has_plugin(p.plugin_id):
                    self._kosh.register_plugin(p)

        # Register capabilities with Kosh; require that owning plugins are registered
        for cap_k, cap_v in self._capabilities.items():
            if not self._kosh.has_capability(cap_k):
                p_id = cap_v.declaration.plugin_id
                if not self._kosh.has_plugin(p_id):
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=(
                            f"Cannot register capability '{cap_k}': owning plugin '{p_id}' is not registered in Kosh. "
                            "Pass explicit PluginInfo via the 'plugins' argument."
                        ),
                    )
                self._dvara.register_capability(cap_v.declaration)

        # Yantra & Manthan
        self._yantra: Yantra = Yantra(self._inventory, darpana=self._darpana)
        for cap in self._capabilities.values():
            if hasattr(cap, "_yantra") and getattr(cap, "_yantra") is None:
                object.__setattr__(cap, "_yantra", self._yantra)

        self._manthan: Manthan = Manthan(registry=self._kosh)

        # Prana & QuarantineStore
        self._prana: Prana = Prana()
        if self._darpana is not None:
            self._prana.register("darpana", self._darpana)
        self._quarantine_store: QuarantineStore = QuarantineStore(
            root=self._runtime_root / "Quarantine",
        )

        # 8b. Validate Smriti Cache
        active_smriti: SmritiCache | None = None
        if smriti is not None:
            if not isinstance(smriti, SmritiCache):
                raise TypeError(f"smriti must be a SmritiCache instance or None, got {type(smriti).__name__}.")
            active_smriti = smriti
        self._smriti: SmritiCache | None = active_smriti

        # Pravaha Dynamic Pipeline Engine
        self._pravaha: Pravaha = Pravaha(
            manthan=self._manthan,
            yantra=self._yantra,
            capabilities=self._capabilities,
            quarantine_store=self._quarantine_store,
            retry_policy=self._retry_policy,
            darpana=self._darpana,
            kavacha=self._kavacha,
            smriti=self._smriti,
        )

        self._is_started: bool = False
        self._is_closed: bool = False

    @property
    def is_started(self) -> bool:
        """Return True if runtime lifecycle has started and not closed."""
        return self._is_started

    @property
    def is_closed(self) -> bool:
        """Return True if runtime lifecycle has been closed."""
        return self._is_closed

    @property
    def settings(self) -> Settings:
        """Return the active Settings."""
        return self._settings

    @property
    def darpana(self) -> Darpana:
        """Return the injected Darpana telemetry service."""
        return self._darpana

    @property
    def smriti(self) -> SmritiCache | None:
        """Return the injected SmritiCache service if configured."""
        return self._smriti

    @property
    def runtime_root(self) -> Path:
        """Return the effective validated runtime root."""
        return self._runtime_root

    @property
    def output_root(self) -> Path:
        """Return the effective validated output root."""
        return self._output_root

    @property
    def input_root(self) -> Path:
        """Return the effective validated input root."""
        return self._input_root

    @property
    def kavacha(self) -> Kavacha:
        """Return the injected Kavacha security service."""
        return self._kavacha

    @property
    def artifact_boundary(self) -> ArtifactBoundary:
        """Return the injected ArtifactBoundary."""
        return self._artifact_boundary

    @property
    def kosh(self) -> Kosh:
        """Return the canonical Kosh registry."""
        return self._kosh

    @property
    def dvara(self) -> Dvara:
        """Return the Dvara registration manager."""
        return self._dvara

    @property
    def yantra(self) -> Yantra:
        """Return the Yantra execution manager."""
        return self._yantra

    @property
    def manthan(self) -> Manthan:
        """Return the Manthan capability resolver."""
        return self._manthan

    @property
    def prana(self) -> Prana:
        """Return the Prana lifecycle manager."""
        return self._prana

    @property
    def quarantine_store(self) -> QuarantineStore:
        """Return the QuarantineStore."""
        return self._quarantine_store

    @property
    def retry_policy(self) -> RetryPolicy:
        """Return the active RetryPolicy."""
        return self._retry_policy

    @property
    def pravaha(self) -> Pravaha:
        """Return the Pravaha pipeline engine."""
        return self._pravaha

    @property
    def capabilities(self) -> Mapping[str, Capability]:
        """Return an immutable snapshot of configured executable capabilities."""
        return dict(self._capabilities)

    def register_component(self, component_id: str, component: Any) -> None:
        """Register a runtime component with Prana for lifecycle coordination."""
        self._prana.register(component_id, component)

    def start(self) -> None:
        """Start registered runtime components in dependency order via Prana."""
        if self._is_closed:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="Agni runtime instance cannot be restarted after close.",
            )
        if not self._is_started:
            self._prana.start_all()
            self._is_started = True

    def close(self) -> None:
        """Close registered runtime components in reverse dependency order via Prana."""
        if self._is_closed:
            return
        self._is_closed = True
        try:
            self._prana.close_all()
        finally:
            self._is_started = False

    def stop(self) -> None:
        """Alias for close()."""
        self.close()

    def __enter__(self) -> Agni:
        """Context manager entry: starts runtime lifecycle."""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit: stops runtime lifecycle."""
        self.close()

    def execute(
        self,
        request: Request,
        context: ExecutionContext | None = None,
    ) -> Result:
        """Execute a canonical Request through the full Agni-wired runtime path.

        Performs:
        1. Input source vs active/effective destination root overlap verification via Kavacha.
        2. Unique run/trace execution identity generation when no explicit context is provided.
        3. Pre-Manthan Darshana identification with Darpana telemetry timing.
        4. Manthan capability plan resolution with Darpana telemetry timing.
        5. RunWorkspace opening via Nabhi ArtifactBoundary for this validated run.
        6. Pravaha dynamic pipeline execution across Yantra and configured capabilities.
        7. Artifact atomic commit of exact payload bytes into Output/<requirement>/Run-... via RunWorkspace.
        8. Run manifest (run-manifest.json) finalization written last.
        9. Returns canonical final Result with confirmed ArtifactRefs from the workspace.

        Args:
            request: Canonical processing request.
            context: Optional execution context for correlation.

        Returns:
            Canonical Result produced by the pipeline with confirmed ArtifactRefs.

        Raises:
            TypeError: On invalid argument types.
            DoshError: On validation, security, resolution, execution, or capability failures.
        """
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")

        if context is not None and not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance or None, got {type(context).__name__}.")

        # 1. Prevent re-ingestion from active staging/runtime or effective output roots via Kavacha
        effective_output_root = (request.output_root or self._output_root).resolve()
        self._kavacha.validate_source_destination_overlap(
            request.inputs,
            (self._runtime_root, effective_output_root),
        )

        t_start_utc = datetime.now(timezone.utc).isoformat()
        t_start_ns = time.perf_counter_ns()

        # 2. Reconcile request and supplied-context cancellation tokens
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

            if context.cancellation_token is not effective_token:
                exec_ctx = ExecutionContext(
                    run_id=context.run_id,
                    request_id=context.request_id,
                    trace_id=context.trace_id,
                    span_id=context.span_id,
                    parent_span_id=context.parent_span_id,
                    profile=context.profile,
                    quarantine_attempt=context.quarantine_attempt,
                    is_retry=context.is_retry,
                    cancellation_token=effective_token,
                    metadata=context.metadata,
                )
            else:
                exec_ctx = context
        else:
            exec_ctx = ExecutionContext(
                run_id=f"run-{uuid.uuid4().hex[:12]}",
                request_id=request.request_id,
                trace_id=f"tr-{uuid.uuid4().hex[:16]}",
                span_id=f"sp-{uuid.uuid4().hex[:8]}",
                profile=request.profile,
                cancellation_token=effective_token,
            )

        # 3. Open RunWorkspace on the canonical ArtifactBoundary for this validated run
        with self._artifact_boundary.begin_run(
            run_id=exec_ctx.run_id,
            requirement=request.requirement,
            output_root=effective_output_root,
            preserve_partial=request.preserve_partial,
            input_sources=request.inputs,
            context=exec_ctx,
        ) as workspace:
            try:
                # Check cancellation at safe boundary before identification
                if exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled:
                    exec_ctx.cancellation_token.check_cancelled()

                # Pre-Manthan Darshana Identification (Timed in Darpana)
                id_scope = (
                    self._darpana.time_scope(
                        context=exec_ctx,
                        phase_name="identification",
                        component="shakti.darshana",
                        attributes={"input_count": len(request.inputs)},
                    )
                    if self._darpana is not None
                    else nullcontext()
                )
                with id_scope:
                    identified_request = identify_request(request)

                # Check cancellation at safe boundary before resolution
                if exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled:
                    exec_ctx.cancellation_token.check_cancelled()

                # Manthan Capability Plan Resolution (Timed in Darpana)
                res_scope = (
                    self._darpana.time_scope(
                        context=exec_ctx,
                        phase_name="resolution",
                        component="nabhi.manthan",
                        attributes={"requirement": identified_request.requirement},
                    )
                    if self._darpana is not None
                    else nullcontext()
                )
                with res_scope:
                    plan = self._manthan.resolve(identified_request)

                # 4. Pravaha Dynamic Pipeline Execution (includes Kavacha security authorization)
                raw_result = self._pravaha.execute(plan, identified_request, exec_ctx)

                # Check cancellation at safe boundary before committing artifacts
                if exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled:
                    exec_ctx.cancellation_token.check_cancelled()

                # 5. Commit declared artifact payloads through Nabhi RunWorkspace
                if raw_result.artifact_payloads:
                    for payload in raw_result.artifact_payloads:
                        if exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled:
                            exec_ctx.cancellation_token.check_cancelled()
                        workspace.commit_artifact(payload.intent, payload.content)

                # Check cancellation at safe boundary before finalization
                if exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled:
                    exec_ctx.cancellation_token.check_cancelled()

                # 6. Finalize workspace and write run-manifest.json last
                workspace.finalize(
                    success=True,
                    provenance=raw_result.provenance,
                    warnings=raw_result.warnings,
                )

                duration_ms = max(0, (time.perf_counter_ns() - t_start_ns) // 1_000_000)
                try:
                    resolved_out = workspace.output_dir.resolve()
                    resolved_root = effective_output_root.resolve()
                    out_dir_ref = (
                        str(resolved_out.relative_to(resolved_root)).replace("\\", "/")
                        if workspace.output_dir
                        else None
                    )
                except (ValueError, OSError):
                    out_dir_ref = str(workspace.output_dir).replace("\\", "/") if workspace.output_dir else None

                self._record_terminal_summary(
                    exec_ctx=exec_ctx,
                    request=request,
                    status="completed",
                    start_time_utc=t_start_utc,
                    duration_ms=duration_ms,
                    artifact_count=len(workspace.committed_artifacts),
                    warning_count=len(raw_result.warnings),
                    output_dir=out_dir_ref,
                )

                # 7. Return final Result with confirmed ArtifactRefs strictly from active workspace
                result_metadata = dict(raw_result.metadata)
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
            except Exception as proc_exc:
                duration_ms = max(0, (time.perf_counter_ns() - t_start_ns) // 1_000_000)
                is_cancelled = (isinstance(proc_exc, DoshError) and bool(proc_exc.context.get("cancelled"))) or (
                    exec_ctx.cancellation_token is not None and exec_ctx.cancellation_token.is_cancelled
                )
                term_status = "cancelled" if is_cancelled else "failed"

                if is_cancelled and self._darpana is not None:
                    from sarathi.darpana import MarutiRecord

                    self._darpana.record_maruti(
                        MarutiRecord(
                            run_id=exec_ctx.run_id,
                            request_id=exec_ctx.request_id,
                            trace_id=exec_ctx.trace_id,
                            span_id=exec_ctx.span_id,
                            phase_name="cancellation",
                            component="agni",
                            timestamp_utc=datetime.now(timezone.utc).isoformat(),
                            duration_ns=0,
                            outcome="failure",
                            attributes={"cancelled": True},
                        )
                    )

                if not workspace.is_finalized:
                    try:
                        workspace.finalize(
                            success=False,
                            status=term_status,
                        )
                    except (OSError, DoshError) as cleanup_exc:
                        if self._darpana is not None:
                            from sarathi.darpana import MarutiRecord

                            self._darpana.record_maruti(
                                MarutiRecord(
                                    run_id=exec_ctx.run_id,
                                    request_id=exec_ctx.request_id,
                                    trace_id=exec_ctx.trace_id,
                                    span_id=exec_ctx.span_id,
                                    phase_name="workspace.finalize_cleanup_failure",
                                    component="agni",
                                    timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                    duration_ns=0,
                                    outcome="failure",
                                    attributes={"error_type": type(cleanup_exc).__name__},
                                )
                            )

                    out_dir_fail = None
                    try:
                        out_dir_fail = str(workspace.output_dir.relative_to(effective_output_root)).replace("\\", "/")
                    except Exception:
                        pass

                    self._record_terminal_summary(
                        exec_ctx=exec_ctx,
                        request=request,
                        status=term_status,
                        start_time_utc=t_start_utc,
                        duration_ms=duration_ms,
                        artifact_count=len(getattr(workspace, "committed_artifacts", ())),
                        warning_count=0,
                        output_dir=out_dir_fail,
                    )
                raise

    def _record_terminal_summary(
        self,
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
        if self._darpana is None or not self._settings.telemetry_history_enabled:
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
                completed_at_utc=datetime.now(timezone.utc).isoformat(),
                duration_ms=duration_ms,
                artifact_count=artifact_count,
                warning_count=warning_count,
                has_masked_identity=False,
                output_dir=output_dir,
            )
            self._darpana.record_run_summary(summary)
        except Exception:
            from sarathi.darpana import MarutiRecord

            self._darpana.record_maruti(
                MarutiRecord(
                    run_id=exec_ctx.run_id,
                    request_id=exec_ctx.request_id,
                    trace_id=exec_ctx.trace_id,
                    span_id=exec_ctx.span_id,
                    phase_name="telemetry.history_persistence_failure",
                    component="agni",
                    timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    duration_ns=0,
                    outcome="failure",
                    attributes={"error": "history_recording_failed"},
                )
            )
