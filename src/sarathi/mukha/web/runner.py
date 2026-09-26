"""Mukha Interactive Run Coordinator and Worker Lifecycle for Sarathi.

Manages interactive background processing runs, concurrency locking, cancellation,
live worker and page progress tracking, and confirmed artifact indexing.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import InputSelectionView, PreflightView, ReviewIntent, RunSummaryView
from sarathi.mukha.web.security import _format_public_error, _sanitize_message
from sarathi.mukha.web.state_builder import get_reviewable_warnings, get_run_telemetry
from sarathi.sankalpa import (
    ArtifactRef,
    CancellationToken,
    CanonicalDocument,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)

if TYPE_CHECKING:
    from sarathi.agni import Agni


class StartRunStatus(StrEnum):
    """Result status of an attempt to start an interactive run."""

    OK = "ok"
    BUSY = "busy"
    INVALID_INPUTS = "invalid_inputs"


@dataclass(frozen=True, slots=True)
class StartRunResponse:
    """Typed result of an attempt to start an interactive run."""

    status: StartRunStatus
    run_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ActiveRunSnapshot:
    """Immutable snapshot of the active run state for consistent view rendering."""

    run_id: str | None
    request: Request | None
    start_ns: int
    is_alive: bool
    terminal_summary: RunSummaryView | None
    terminal_status: str | None
    live_progress: dict[str, Any]
    live_workers: dict[str, dict[str, Any]]
    file_progress: dict[str, dict[str, Any]]


class RunCoordinator:
    """Coordinates background execution runs and tracks live execution progress."""

    def __init__(self, agni: Agni) -> None:
        self._agni = agni
        self._lock = threading.RLock()
        self._active_run_id: str | None = None
        self._active_request: Request | None = None
        self._active_token: CancellationToken | None = None
        self._active_thread: threading.Thread | None = None
        self._active_start_ns: int = 0
        self._last_result: Result | None = None
        self._last_result_run_id: str | None = None
        self._terminal_summary: RunSummaryView | None = None
        self._terminal_status: str | None = None
        self._confirmed_artifacts: dict[str, dict[str, ArtifactRef]] = {}
        self._run_aliases: dict[str, str] = {}
        self._run_output_roots: dict[str, Path] = {}
        self._live_progress: dict[str, Any] = {}
        self._live_workers: dict[str, dict[str, Any]] = {}
        self._file_progress: dict[str, dict[str, Any]] = {}
        self._review_intents: dict[str, ReviewIntent] = {}
        self._unassociated_warning_count: int = 0
        self._state_revision: int = 1
        self._listeners: set[Callable[[], None]] = set()
        self._intake_selection: InputSelectionView | None = None
        self._intake_preflight: PreflightView | None = None
        self._input_path_registry: dict[str, Path] = {}
        self._run_summaries: dict[str, RunSummaryView] = {}
        self._auto_discover_input_root()

    def _auto_discover_input_root(self) -> None:
        """Auto-discover files in agni.input_root and pre-populate initial intake."""
        if not self._agni.input_root.is_dir():
            return
        try:
            inputs, selection, preflight = MukhaPresenter.intake_from_paths(
                [self._agni.input_root],
                kavacha=self._agni.kavacha,
                runtime_root=self._agni.runtime_root,
                output_root=self._agni.output_root,
                recursive=True,
            )
            with self._lock:
                self._input_path_registry.clear()
            self.set_intake_selection(selection, inputs, preflight=preflight)
        except Exception:
            pass

    def rescan_input_root(self) -> tuple[InputSelectionView | None, PreflightView | None]:
        """Re-scan agni.input_root if runner is idle and refresh cached intake."""
        if not self.is_busy():
            self._auto_discover_input_root()
        return self.get_intake_selection(), self.get_intake_preflight()

    def reset(self) -> None:
        """Reset internal run state and caches for clean lifecycle transitions."""
        with self._lock:
            if self._active_thread is not None and self._active_thread.is_alive():
                if self._active_token is not None:
                    self._active_token.cancel()
                self._active_thread.join(timeout=1.0)
            self._active_run_id = None
            self._active_request = None
            self._active_token = None
            self._active_thread = None
            self._active_start_ns = 0
            self._last_result = None
            self._last_result_run_id = None
            self._terminal_summary = None
            self._terminal_status = None
            self._confirmed_artifacts.clear()
            self._run_aliases.clear()
            self._run_output_roots.clear()
            self._live_progress.clear()
            self._live_workers.clear()
            self._file_progress.clear()
            self._review_intents.clear()
            self._unassociated_warning_count = 0
            self._bump_revision()
            self._intake_selection = None
            self._intake_preflight = None
            self._input_path_registry.clear()
            self._run_summaries.clear()
        self._auto_discover_input_root()

    @property
    def state_revision(self) -> int:
        """Monotonically increasing state revision counter."""
        with self._lock:
            return self._state_revision

    def _bump_revision(self) -> None:
        """Increment state revision and notify registered listeners."""
        self._state_revision += 1
        listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                pass

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback invoked when state or revision changes. Returns an unregister function."""
        with self._lock:
            self._listeners.add(callback)

        def _unregister() -> None:
            with self._lock:
                self._listeners.discard(callback)

        return _unregister

    def is_busy(self) -> bool:
        """Return True if an interactive processing run is currently active on background worker thread."""
        with self._lock:
            return self._active_thread is not None and self._active_thread.is_alive()

    def set_intake_selection(
        self,
        input_selection: InputSelectionView | None,
        inputs: Sequence[InputRef] | None = None,
        preflight: PreflightView | None = None,
    ) -> None:
        """Cache intake input selection and register known input paths for safe preview."""
        with self._lock:
            self._intake_selection = input_selection
            self._intake_preflight = preflight
            if inputs:
                for inp in inputs:
                    if inp.source_path:
                        self._input_path_registry[inp.input_id] = Path(inp.source_path).resolve()
            if input_selection and input_selection.items:
                for item in input_selection.items:
                    if item.source_path:
                        self._input_path_registry[item.input_id] = Path(item.source_path).resolve()
            self._bump_revision()

    def get_intake_selection(self) -> InputSelectionView | None:
        """Return cached intake selection view."""
        with self._lock:
            return self._intake_selection

    def get_intake_preflight(self) -> PreflightView | None:
        """Return cached intake preflight view."""
        with self._lock:
            return self._intake_preflight

    def get_input_path(self, input_id: str) -> Path | None:
        """Resolve absolute source Path for an intake input_id."""
        with self._lock:
            path = self._input_path_registry.get(input_id)
            if path and path.is_file():
                return path
            if self._active_request:
                for inp in self._active_request.inputs:
                    if inp.input_id == input_id and inp.source_path:
                        resolved = Path(inp.source_path).resolve()
                        if resolved.is_file():
                            self._input_path_registry[input_id] = resolved
                            return resolved
            return None

    def get_run_summary(self, run_id: str) -> RunSummaryView | None:
        """Retrieve terminal run summary by run ID or request ID."""
        with self._lock:
            if self._terminal_summary and (
                self._terminal_summary.run_id == run_id or getattr(self._terminal_summary, "request_id", None) == run_id
            ):
                return self._terminal_summary
            if run_id in self._run_summaries:
                return self._run_summaries[run_id]
            for s in self._run_summaries.values():
                if getattr(s, "run_id", None) == run_id or getattr(s, "request_id", None) == run_id:
                    return s
            return None

    def apply_review_intent(self, intent: ReviewIntent) -> bool:
        """Apply and record a human review decision, failing closed on invalid intents."""
        with self._lock:
            # 1. Reject missing or whitespace-only identity
            if not intent.item_id or not intent.item_id.strip():
                return False
            if not intent.attempt_id or not intent.attempt_id.strip():
                return False

            # 2. Reject unsupported review actions (validate_edit and retry lack runtime capability support)
            if intent.action_id not in ("accept", "unresolved"):
                return False

            # 3. Enforce run scoping if run_id provided
            target_run_id = (
                self._last_result_run_id
                or (self._terminal_summary.run_id if self._terminal_summary else None)
                or self._active_run_id
            )
            if intent.run_id:
                if target_run_id and intent.run_id != target_run_id:
                    return False

            # 4. Check that item exists in reviewable warnings
            if self._last_result is None or not self._last_result.warnings:
                return False

            reviewable = get_reviewable_warnings(self._last_result)
            matched_warning = None
            orig_match_idx = None
            for orig_idx, w in reviewable:
                if f"rev-{orig_idx}" == intent.item_id:
                    matched_warning = w
                    orig_match_idx = orig_idx
                    break

            if matched_warning is None:
                return False

            # 5. Check attempt matching if warning has span_id / attempt
            expected_att = (
                getattr(matched_warning, "span_id", "")
                or (matched_warning.context.get("attempt_id", "") if matched_warning.context else "")
                or f"att-{target_run_id or 'run'}-{orig_match_idx}"
            )
            if intent.attempt_id != expected_att:
                return False

            # 6. Check state revision if expected_revision provided
            if intent.expected_revision is not None and intent.expected_revision != self._state_revision:
                return False

            # 7. Check duplicate identical submission
            existing = self._review_intents.get(intent.item_id)
            if (
                existing is not None
                and existing.action_id == intent.action_id
                and existing.proposed_value == intent.proposed_value
            ):
                return False

            self._review_intents[intent.item_id] = intent
            self._bump_revision()
            return True

    def get_review_intents(self) -> dict[str, ReviewIntent]:
        """Return a snapshot of applied review decisions."""
        with self._lock:
            return dict(self._review_intents)

    def clear_history(self) -> None:
        """Clear cached terminal run summaries and historical run references."""
        with self._lock:
            self._run_summaries.clear()
            self._confirmed_artifacts.clear()
            self._run_output_roots.clear()
            self._review_intents.clear()
            if not (self._active_thread is not None and self._active_thread.is_alive()):
                self._terminal_summary = None
                self._terminal_status = None
                self._last_result = None
                self._last_result_run_id = None
            self._bump_revision()

    @property
    def last_result(self) -> Result | None:
        """Return the Result from the most recent run."""
        with self._lock:
            return self._last_result

    @property
    def terminal_summary(self) -> RunSummaryView | None:
        """Return the most recent terminal run summary."""
        with self._lock:
            return self._terminal_summary

    @property
    def terminal_status(self) -> str | None:
        """Return the most recent terminal status."""
        with self._lock:
            return self._terminal_status

    def get_active_snapshot(self) -> ActiveRunSnapshot:
        """Capture an atomic snapshot of current run tracking state."""
        with self._lock:
            is_alive = self._active_thread is not None and self._active_thread.is_alive()
            return ActiveRunSnapshot(
                run_id=self._active_run_id,
                request=self._active_request,
                start_ns=self._active_start_ns,
                is_alive=is_alive,
                terminal_summary=self._terminal_summary,
                terminal_status=self._terminal_status,
                live_progress=dict(self._live_progress),
                live_workers=dict(self._live_workers),
                file_progress=dict(self._file_progress),
            )

    def get_confirmed_artifact(self, run_id: str, artifact_id: str) -> ArtifactRef | None:
        """Look up confirmed ArtifactRef by run ID and artifact ID with strict run scoping."""
        with self._lock:
            res = self._confirmed_artifacts.get(run_id, {}).get(artifact_id)
            if res is not None:
                return res
            aliased_id = self._run_aliases.get(run_id)
            if aliased_id and aliased_id in self._confirmed_artifacts:
                res = self._confirmed_artifacts[aliased_id].get(artifact_id)
                if res is not None:
                    return res

        return self._restore_artifact_from_manifest(run_id, artifact_id)

    def _restore_artifact_from_manifest(self, run_id: str, artifact_id: str) -> ArtifactRef | None:
        """Restore an ArtifactRef from the run's on-disk manifest if not cached in memory."""
        target_dir: Path | None = None
        with self._lock:
            target_dir = self._run_output_roots.get(run_id)
            if target_dir is None and run_id in self._run_aliases:
                target_dir = self._run_output_roots.get(self._run_aliases[run_id])

        if target_dir is None and self._agni.darpana is not None:
            terminal = self._agni.darpana.get_run_summary(run_id)
            if terminal is not None and terminal.output_dir:
                target_dir = (self._agni.output_root / terminal.output_dir).resolve()

        if target_dir is None:
            cand = (self._agni.output_root / run_id).resolve()
            if cand.is_dir():
                target_dir = cand

        if target_dir is None or not target_dir.is_dir():
            return None

        output_root = self._agni.output_root.resolve()
        if target_dir != output_root and output_root not in target_dir.parents:
            return None

        manifest_path = target_dir / "run-manifest.json"
        if not manifest_path.is_file():
            return None

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest_data = json.load(f)

            m_run_id = manifest_data.get("run_id")
            if m_run_id and m_run_id != run_id:
                with self._lock:
                    is_valid_alias = (
                        self._run_aliases.get(run_id) == m_run_id or self._run_aliases.get(m_run_id) == run_id
                    )
                if not is_valid_alias:
                    if self._agni.darpana is not None:
                        term = self._agni.darpana.get_run_summary(run_id)
                        if term is None or (term.run_id != m_run_id and term.request_id != run_id):
                            return None
                    else:
                        return None

            for art in manifest_data.get("artifacts", []):
                if art.get("artifact_id") == artifact_id:
                    rel_p = art.get("relative_path", "")
                    full_p = (target_dir / rel_p).resolve()
                    if full_p != output_root and output_root not in full_p.parents:
                        return None
                    if not full_p.is_file():
                        return None

                    art_ref = ArtifactRef(
                        artifact_id=art.get("artifact_id", ""),
                        path=full_p,
                        role=art.get("role", "primary"),
                        media_type=art.get("media_type", "application/octet-stream"),
                        size_bytes=art.get("size_bytes", 0),
                        checksum_sha256=art.get("checksum_sha256", ""),
                    )
                    with self._lock:
                        if run_id not in self._confirmed_artifacts:
                            self._confirmed_artifacts[run_id] = {}
                        self._confirmed_artifacts[run_id][artifact_id] = art_ref
                        if m_run_id:
                            self._run_aliases[run_id] = m_run_id
                            self._run_aliases[m_run_id] = run_id
                            if m_run_id not in self._confirmed_artifacts:
                                self._confirmed_artifacts[m_run_id] = {}
                            self._confirmed_artifacts[m_run_id][artifact_id] = art_ref
                    return art_ref
        except Exception:
            return None
        return None

    def start_run(
        self,
        paths: list[Path],
        requirement: str = "read_native",
        profile: ExecutionProfile = ExecutionProfile.INSTANT,
        recursive: bool = True,
        custom_options: Mapping[str, Any] | None = None,
    ) -> StartRunResponse:
        """Start a document processing run on a background worker thread.

        Enforces single interactive run concurrency. Returns StartRunResponse.
        """
        if self.is_busy():
            return StartRunResponse(
                status=StartRunStatus.BUSY,
                error_message="An interactive processing run is already active.",
            )

        effective_paths = list(paths) if paths else []
        if not effective_paths:
            with self._lock:
                if self._intake_selection and self._intake_selection.items:
                    effective_paths = [
                        item.source_path
                        for item in self._intake_selection.items
                        if item.is_eligible and item.source_path
                    ]
            if not effective_paths and self._agni.input_root.is_dir():
                effective_paths = [str(self._agni.input_root)]

        # Intake and resolve input references outside lock
        inputs, selection, preflight = MukhaPresenter.intake_from_paths(
            effective_paths,
            kavacha=self._agni.kavacha,
            runtime_root=self._agni.runtime_root,
            output_root=self._agni.output_root,
            recursive=recursive,
        )
        if not inputs:
            return StartRunResponse(
                status=StartRunStatus.INVALID_INPUTS,
                error_message="No eligible input documents discovered.",
            )

        with self._lock:
            if self._active_thread is not None and self._active_thread.is_alive():
                return StartRunResponse(
                    status=StartRunStatus.BUSY,
                    error_message="An interactive processing run is already active.",
                )

            self._intake_selection = selection
            self._intake_preflight = preflight
            for inp in inputs:
                if inp.source_path:
                    self._input_path_registry[inp.input_id] = Path(inp.source_path).resolve()

            # Reset live progress tracking and ephemeral review intents for active run
            self._live_progress = {}
            self._live_workers = {}
            self._file_progress = {}
            self._review_intents.clear()
            self._unassociated_warning_count = 0

            def _on_progress(
                file_display_name: str,
                page_number: int,
                total_pages: int,
                worker_id: str = "1",
                stage: str = "Optical Character Recognition (OCR)",
                device_type: str | None = None,
                input_id: str = "",
                **kwargs: Any,
            ) -> None:
                with self._lock:
                    now = time.perf_counter_ns()
                    dev = device_type or ""
                    existing_w = self._live_workers.get(str(worker_id))
                    is_same = (
                        existing_w is not None
                        and existing_w.get("stage") == stage
                        and existing_w.get("file_display_name") == file_display_name
                    )
                    w_start = existing_w["started_ns"] if is_same else now
                    w_info = {
                        "worker_id": str(worker_id),
                        "file_display_name": file_display_name,
                        "page_number": page_number,
                        "total_pages": total_pages,
                        "stage": stage,
                        "device_type": dev,
                        "started_ns": w_start,
                        "updated_ns": now,
                        "input_id": input_id,
                    }
                    self._live_progress = w_info
                    self._live_workers[str(worker_id)] = w_info

                    key = input_id or file_display_name
                    existing_f = self._file_progress.get(key)
                    f_start = existing_f.get("started_ns", now) if existing_f else now
                    info = {
                        "input_id": input_id,
                        "file_display_name": file_display_name,
                        "page_number": page_number,
                        "total_pages": total_pages,
                        "stage": stage,
                        "device_type": dev,
                        "status": "RUNNING",
                        "started_ns": f_start,
                        "updated_ns": now,
                    }
                    self._file_progress[key] = info
                    if input_id and file_display_name:
                        self._file_progress[file_display_name] = info
                    self._bump_revision()

            effective_custom_options = dict(custom_options or {})
            effective_custom_options["progress_callback"] = _on_progress

            req_metadata = {}
            if effective_custom_options.get("direction"):
                req_metadata["direction"] = effective_custom_options["direction"]

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            token = CancellationToken()
            request = Request(
                request_id=run_id,
                requirement=requirement,
                inputs=inputs,
                profile=profile,
                cancellation_token=token,
                custom_options=effective_custom_options,
                metadata=req_metadata,
            )

            self._active_run_id = run_id
            self._active_request = request
            self._active_token = token
            self._active_start_ns = time.perf_counter_ns()
            self._last_result = None
            self._terminal_summary = None
            self._terminal_status = None
            self._bump_revision()

            def _worker() -> None:
                nonlocal run_id, request
                try:
                    result = self._agni.execute(request)
                    maruti_recs, pramana_recs = get_run_telemetry(self._agni, run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)

                    self._finalize_successful_run(
                        run_id=run_id,
                        request=request,
                        result=result,
                        maruti_recs=maruti_recs,
                        pramana_recs=pramana_recs,
                        wall_time_ns=wall_time_ns,
                    )
                except DoshError as dosh_err:
                    is_cancelled = (
                        (request.cancellation_token and request.cancellation_token.is_cancelled)
                        or bool(dosh_err.context.get("cancelled"))
                        or "cancelled" in dosh_err.message.lower()
                    )
                    status = "CANCELLED" if is_cancelled else "FAILED"
                    failures = ("Execution cancelled by user.",) if is_cancelled else (_format_public_error(dosh_err),)
                    maruti_recs, pramana_recs = get_run_telemetry(self._agni, run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)
                    summary = MukhaPresenter.build_summary_view(
                        run_id=run_id,
                        status=status,
                        wall_time_ns=wall_time_ns,
                        request=request,
                        result=None,
                        failures=failures,
                        maruti_records=maruti_recs,
                        pramana_records=pramana_recs,
                    )
                    with self._lock:
                        for inp in request.inputs:
                            curr = self._file_progress.get(inp.input_id) or self._file_progress.get(inp.display_name)
                            if curr and curr.get("status") in ("RUNNING", "PENDING"):
                                curr["status"] = status
                                curr["stage"] = "Cancelled" if is_cancelled else "Failed"
                        self._terminal_status = status
                        self._terminal_summary = summary
                        self._run_summaries[run_id] = summary
                        self._prune_old_runs()
                except Exception as exc:
                    import traceback

                    traceback.print_exc()
                    sanitized_detail = _sanitize_message(str(exc).strip().splitlines()[-1] if str(exc).strip() else "")
                    failure_msg = (
                        f"EXECUTION_FAILED: {type(exc).__name__}: {sanitized_detail}"
                        if sanitized_detail
                        else "EXECUTION_FAILED: An internal error occurred during processing."
                    )
                    maruti_recs, pramana_recs = get_run_telemetry(self._agni, run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)
                    summary = MukhaPresenter.build_summary_view(
                        run_id=run_id,
                        status="FAILED",
                        wall_time_ns=wall_time_ns,
                        request=request,
                        result=None,
                        failures=(failure_msg,),
                        maruti_records=maruti_recs,
                        pramana_records=pramana_recs,
                    )
                    with self._lock:
                        for inp in request.inputs:
                            curr = self._file_progress.get(inp.input_id) or self._file_progress.get(inp.display_name)
                            if curr and curr.get("status") in ("RUNNING", "PENDING"):
                                curr["status"] = "FAILED"
                                curr["stage"] = "Failed"
                        self._terminal_status = "FAILED"
                        self._terminal_summary = summary
                        self._run_summaries[run_id] = summary
                        self._prune_old_runs()
                finally:
                    with self._lock:
                        if self._terminal_summary is None:
                            for inp in request.inputs:
                                curr = self._file_progress.get(inp.input_id) or self._file_progress.get(
                                    inp.display_name
                                )
                                if curr and curr.get("status") in ("RUNNING", "PENDING"):
                                    curr["status"] = "FAILED"
                                    curr["stage"] = "Failed"
                            maruti_recs, pramana_recs = get_run_telemetry(self._agni, run_id)
                            wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)
                            self._terminal_status = "FAILED"
                            self._terminal_summary = MukhaPresenter.build_summary_view(
                                run_id=run_id,
                                status="FAILED",
                                wall_time_ns=wall_time_ns,
                                request=request,
                                result=None,
                                failures=("EXECUTION_FAILED: Worker thread terminated unexpectedly.",),
                                maruti_records=maruti_recs,
                                pramana_records=pramana_recs,
                            )
                            self._run_summaries[run_id] = self._terminal_summary
                            self._prune_old_runs()
                        self._live_workers.clear()
                        self._active_thread = None
                        self._bump_revision()

            self._active_thread = threading.Thread(
                target=_worker,
                name=f"MukhaWorker-{run_id}",
                daemon=True,
            )
            self._active_thread.start()
            return StartRunResponse(status=StartRunStatus.OK, run_id=run_id)

    def _finalize_successful_run(
        self,
        run_id: str,
        request: Request,
        result: Result,
        maruti_recs: Any,
        pramana_recs: Any,
        wall_time_ns: int,
    ) -> None:
        """Process successful result, update live progress, and record terminal summary."""
        with self._lock:
            self._last_result = result
            self._last_result_run_id = run_id
            if result.metadata.get("output_dir"):
                self._run_output_roots[run_id] = Path(result.metadata["output_dir"])

            context_run_id = result.metadata.get("run_id")
            if context_run_id and str(context_run_id) != run_id:
                self._run_aliases[run_id] = str(context_run_id)
                self._run_aliases[str(context_run_id)] = run_id
            # Populate confirmed artifacts for download
            if result.artifacts:
                self._confirmed_artifacts[run_id] = {art.artifact_id: art for art in result.artifacts}
                if context_run_id and str(context_run_id) != run_id:
                    self._confirmed_artifacts[str(context_run_id)] = self._confirmed_artifacts[run_id]

            # Correlate warnings per input
            input_warn_counts: dict[str, int] = {inp.input_id: 0 for inp in request.inputs}
            unassociated_warns = 0
            for w in result.warnings:
                w_inp = w.context.get("input_id") or w.context.get("source_input_id") or w.context.get("source_file")
                if w_inp and w_inp in input_warn_counts:
                    input_warn_counts[w_inp] += 1
                else:
                    unassociated_warns += 1

            self._unassociated_warning_count = unassociated_warns

            # Map produced document outputs to inputs
            doc_map: dict[str, Any] = {}
            contributing_inputs: set[str] = set()

            if isinstance(result.data, CanonicalDocument):
                doc_map[result.data.source_input_id] = result.data
                contributing_inputs.add(result.data.source_input_id)
            elif isinstance(result.data, (tuple, list)):
                for item in result.data:
                    if isinstance(item, CanonicalDocument):
                        doc_map[item.source_input_id] = item
                        contributing_inputs.add(item.source_input_id)
                    elif hasattr(item, "source_input_id") and item.source_input_id:
                        contributing_inputs.add(str(item.source_input_id))

            # Gather contributing inputs and outcomes from result metadata contract
            capability_outcomes = dict(result.metadata.get("input_outcomes") or {})
            contributing_meta = result.metadata.get("contributing_input_ids")
            if contributing_meta:
                contributing_inputs.update(str(cid) for cid in contributing_meta)

            # Also gather contributing inputs from result provenance
            if result.provenance:
                for p in result.provenance:
                    if p.source_input_id:
                        contributing_inputs.add(p.source_input_id)

            successful_cnt = 0
            warning_cnt = 0
            failed_cnt = 0

            is_run_cached = bool(result.metadata.get("cached")) if result and result.metadata else False
            if not is_run_cached and maruti_recs:
                is_run_cached = any(
                    r.phase_name == "cache.lookup" and r.attributes.get("outcome") == "hit" for r in maruti_recs
                )
            stage_label = "Completed (Cached)" if is_run_cached else "Completed"

            for inp in request.inputs:
                existing = self._file_progress.get(inp.input_id) or self._file_progress.get(inp.display_name, {})
                start_t = existing.get("started_ns")
                duration = existing.get("duration_ns")
                w_count = input_warn_counts.get(inp.input_id, 0)

                # Determine factual per-input status
                if inp.input_id in capability_outcomes:
                    explicit_status = str(capability_outcomes[inp.input_id]).upper()
                    if explicit_status in ("SUCCESS", "COMPLETED"):
                        f_stat = "WARNING" if w_count > 0 else "SUCCESS"
                    elif explicit_status in ("WARNING",):
                        f_stat = "WARNING"
                    else:
                        f_stat = "FAILED"
                else:
                    if len(request.inputs) > 1:
                        has_input_doc = inp.input_id in doc_map
                        has_input_artifact = (
                            any(
                                str(art.metadata.get("source_input_id", "")) == inp.input_id
                                or str(art.metadata.get("input_id", "")) == inp.input_id
                                or inp.input_id in (art.metadata.get("source_input_ids") or ())
                                for art in result.artifacts
                            )
                            if result.artifacts
                            else False
                        )
                        has_aggregate_credit = any(
                            bool(art.metadata.get("is_aggregate")) for art in result.artifacts
                        ) and (inp.input_id in contributing_inputs or not contributing_inputs)
                        has_output = has_input_doc or has_input_artifact or has_aggregate_credit
                    else:
                        has_output = inp.input_id in doc_map or result.data is not None or bool(result.artifacts)

                    if not has_output:
                        f_stat = "FAILED"
                    elif w_count > 0:
                        f_stat = "WARNING"
                    else:
                        f_stat = "SUCCESS"

                if f_stat == "SUCCESS":
                    successful_cnt += 1
                elif f_stat == "WARNING":
                    warning_cnt += 1
                else:
                    failed_cnt += 1

                info = {
                    "input_id": inp.input_id,
                    "file_display_name": inp.display_name,
                    "status": f_stat,
                    "stage": stage_label,
                    "started_ns": start_t,
                    "duration_ns": duration,
                    "warning_count": w_count,
                    "cached": is_run_cached,
                }
                self._file_progress[inp.input_id] = info
                self._file_progress[inp.display_name] = info

            # Determine factual overall run status
            if failed_cnt > 0 and successful_cnt == 0 and warning_cnt == 0:
                overall_status = "FAILED"
            elif failed_cnt > 0:
                overall_status = "PARTIAL"
            elif warning_cnt > 0 or unassociated_warns > 0:
                overall_status = "WARNING"
            else:
                overall_status = "SUCCESS"

            summary = MukhaPresenter.build_summary_view(
                run_id=run_id,
                status=overall_status,
                wall_time_ns=wall_time_ns,
                request=request,
                result=result,
                successful_files=successful_cnt,
                warning_files=warning_cnt,
                failed_files=failed_cnt,
                maruti_records=maruti_recs,
                pramana_records=pramana_recs,
                unassociated_warning_count=unassociated_warns,
            )
            self._terminal_status = overall_status
            self._terminal_summary = summary
            self._run_summaries[run_id] = summary
            if context_run_id and str(context_run_id) != run_id:
                self._run_summaries[str(context_run_id)] = summary
            self._prune_old_runs()

    def _prune_old_runs(self, max_retained: int = 100) -> None:
        """Keep in-memory state bounded by pruning historical run records."""
        if len(self._run_summaries) > max_retained:
            excess = len(self._run_summaries) - max_retained
            oldest_keys = list(self._run_summaries.keys())[:excess]
            for r_id in oldest_keys:
                self._run_summaries.pop(r_id, None)
                self._confirmed_artifacts.pop(r_id, None)
                self._run_output_roots.pop(r_id, None)
                alias = self._run_aliases.pop(r_id, None)
                if alias:
                    self._run_aliases.pop(alias, None)
                    self._confirmed_artifacts.pop(alias, None)
                    self._run_summaries.pop(alias, None)

    def cancel_run(self, run_id: str) -> bool:
        """Cooperatively signal cancellation for the active run."""
        with self._lock:
            if (
                self._active_run_id == run_id
                and self._active_token is not None
                and self._active_thread is not None
                and self._active_thread.is_alive()
            ):
                self._active_token.cancel()
                self._bump_revision()
                return True
            return False

    def reveal_output_directory(self, run_id: str) -> bool:
        """Safely reveal the confirmed run output folder in Windows Explorer / OS file manager in the foreground."""
        # Resolve target directory with fallbacks
        with self._lock:
            target_dir = self._run_output_roots.get(run_id)
            if (target_dir is None or not target_dir.is_dir()) and self._last_result:
                out_dir = self._last_result.metadata.get("output_dir")
                if out_dir:
                    target_dir = Path(out_dir)
            if target_dir is None or not target_dir.is_dir():
                artifacts = self._confirmed_artifacts.get(run_id)
                if artifacts:
                    first_art = next(iter(artifacts.values()), None)
                    if first_art:
                        target_dir = Path(first_art.path).parent
            if target_dir is None or not target_dir.is_dir():
                return False
        try:
            if sys.platform == "win32":
                # 1. Immediately launch Explorer process
                subprocess.Popen(["explorer.exe", str(target_dir)])

                # 2. Asynchronously force Explorer window into foreground
                def _bring_to_foreground() -> None:
                    try:
                        ps_code = r"""
$target = [System.IO.Path]::GetFullPath($env:SARATHI_TARGET_DIR).TrimEnd('\').ToLower()
$targetUri = ([System.Uri]$target).AbsoluteUri.ToLower().TrimEnd('/')

$csharp = @'
using System;
using System.Runtime.InteropServices;
public class Win32Foreground {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, IntPtr ProcessId);
    [DllImport("kernel32.dll")]
    public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")]
    public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern void SwitchToThisWindow(IntPtr hWnd, bool fUnknown);
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")]
    public static extern bool SystemParametersInfo(uint uiAction, uint uiParam, IntPtr pvParam, uint fWinIni);

    public static void ForceForeground(IntPtr hWnd) {
        if (hWnd == IntPtr.Zero) return;
        try {
            SystemParametersInfo(0x2001, 0, IntPtr.Zero, 0x0003); // SPI_SETFOREGROUNDLOCKTIMEOUT
        } catch {}

        IntPtr fg = GetForegroundWindow();
        uint fgThread = GetWindowThreadProcessId(fg, IntPtr.Zero);
        uint curThread = GetCurrentThreadId();

        bool attached = false;
        if (fgThread != 0 && fgThread != curThread) {
            attached = AttachThreadInput(curThread, fgThread, true);
        }

        try {
            keybd_event(0x12, 0, 0, UIntPtr.Zero);
            keybd_event(0x12, 0, 2, UIntPtr.Zero);

            ShowWindowAsync(hWnd, 9); // SW_RESTORE
            SetForegroundWindow(hWnd);
            BringWindowToTop(hWnd);
            SwitchToThisWindow(hWnd, true);
        } finally {
            if (attached) {
                AttachThreadInput(curThread, fgThread, false);
            }
        }
    }
}
'@
try { Add-Type -TypeDefinition $csharp -ErrorAction SilentlyContinue } catch {}

$shell = New-Object -ComObject Shell.Application
$wshell = New-Object -ComObject WScript.Shell
$activated = $false

for ($i = 0; $i -lt 12; $i++) {
    foreach ($w in $shell.Windows()) {
        $loc = ''
        try { $loc = [System.Uri]::UnescapeDataString($w.LocationURL).ToLower().TrimEnd('/') } catch {}
        if ($loc -and ($loc -eq $targetUri -or $loc -like ($targetUri + '/*'))) {
            $hwnd = [IntPtr]$w.HWND
            [Win32Foreground]::ForceForeground($hwnd)
            try { $wshell.AppActivate([int]$hwnd) | Out-Null } catch {}
            $activated = $true
            break
        }
    }
    if ($activated) { break }
    Start-Sleep -Milliseconds 120
}

if (-not $activated) {
    $folderName = Split-Path -Leaf $target
    try { $wshell.AppActivate($folderName) | Out-Null } catch {}
}
"""
                        env = os.environ.copy()
                        env["SARATHI_TARGET_DIR"] = str(target_dir)
                        b64 = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
                        subprocess.run(
                            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", b64],
                            env=env,
                            capture_output=True,
                            timeout=6,
                            check=False,
                        )
                    except Exception:
                        pass

                threading.Thread(target=_bring_to_foreground, daemon=True).start()
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
            return True
        except Exception:
            return False
