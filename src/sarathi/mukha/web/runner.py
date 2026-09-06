"""Mukha Interactive Run Coordinator and Worker Lifecycle for Sarathi V2.

Manages interactive background processing runs, concurrency locking, cancellation,
live worker and page progress tracking, and confirmed artifact indexing.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.dosh import DoshError
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import RunSummaryView
from sarathi.mukha.web.http_handler import (
    StartRunResponse,
    StartRunStatus,
    _format_public_error,
)
from sarathi.mukha.web.state_builder import get_run_telemetry
from sarathi.sankalpa import (
    ArtifactRef,
    CancellationToken,
    CanonicalDocument,
    ExecutionProfile,
    Request,
    Result,
)

if TYPE_CHECKING:
    from sarathi.agni import Agni


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
        self._lock = threading.Lock()
        self._active_run_id: str | None = None
        self._active_request: Request | None = None
        self._active_token: CancellationToken | None = None
        self._active_thread: threading.Thread | None = None
        self._active_start_ns: int = 0
        self._last_result: Result | None = None
        self._terminal_summary: RunSummaryView | None = None
        self._terminal_status: str | None = None
        self._confirmed_artifacts: dict[str, dict[str, ArtifactRef]] = {}
        self._run_output_roots: dict[str, Path] = {}
        self._live_progress: dict[str, Any] = {}
        self._live_workers: dict[str, dict[str, Any]] = {}
        self._file_progress: dict[str, dict[str, Any]] = {}

    def is_busy(self) -> bool:
        """Return True if an interactive processing run is currently active on background worker thread."""
        with self._lock:
            return self._active_thread is not None and self._active_thread.is_alive()

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
        """Look up confirmed ArtifactRef by run ID and artifact ID."""
        with self._lock:
            return self._confirmed_artifacts.get(run_id, {}).get(artifact_id)

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

        # Intake and resolve input references outside lock
        inputs, _, _ = MukhaPresenter.intake_from_paths(
            paths,
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

            # Reset live progress tracking for active run
            self._live_progress = {}
            self._live_workers = {}
            self._file_progress = {}

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
                    w_start = existing_w.get("started_ns", now) if existing_w else now
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

            effective_custom_options = dict(custom_options or {})
            effective_custom_options["progress_callback"] = _on_progress

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            token = CancellationToken()
            request = Request(
                request_id=run_id,
                requirement=requirement,
                inputs=inputs,
                profile=profile,
                cancellation_token=token,
                custom_options=effective_custom_options,
            )

            self._active_run_id = run_id
            self._active_request = request
            self._active_token = token
            self._active_start_ns = time.perf_counter_ns()
            self._last_result = None
            self._terminal_summary = None
            self._terminal_status = None

            def _worker() -> None:
                nonlocal run_id, request
                try:
                    result = self._agni.execute(request)
                    maruti_recs, pramana_recs = get_run_telemetry(self._agni, run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)

                    with self._lock:
                        self._last_result = result
                        if result.metadata.get("output_dir"):
                            self._run_output_roots[run_id] = Path(result.metadata["output_dir"])

                        # Populate confirmed artifacts for download
                        if result.artifacts:
                            self._confirmed_artifacts[run_id] = {art.artifact_id: art for art in result.artifacts}

                        # Correlate warnings per input
                        input_warn_counts: dict[str, int] = {inp.input_id: 0 for inp in request.inputs}
                        unassociated_warns = 0
                        for w in result.warnings:
                            w_inp = (
                                w.context.get("input_id")
                                or w.context.get("source_input_id")
                                or w.context.get("source_file")
                            )
                            if w_inp and w_inp in input_warn_counts:
                                input_warn_counts[w_inp] += 1
                            else:
                                unassociated_warns += 1

                        if unassociated_warns > 0:
                            for inp_id in input_warn_counts:
                                input_warn_counts[inp_id] += unassociated_warns

                        # Map produced document outputs to inputs
                        doc_map: dict[str, Any] = {}
                        if isinstance(result.data, CanonicalDocument):
                            doc_map[result.data.source_input_id] = result.data
                        elif isinstance(result.data, (tuple, list)):
                            for doc in result.data:
                                if isinstance(doc, CanonicalDocument):
                                    doc_map[doc.source_input_id] = doc

                        successful_cnt = 0
                        warning_cnt = 0
                        failed_cnt = 0

                        for inp in request.inputs:
                            existing = (
                                self._file_progress.get(inp.input_id)
                                or self._file_progress.get(inp.display_name, {})
                            )
                            start_t = existing.get("started_ns", self._active_start_ns)
                            duration = existing.get("duration_ns", max(0, time.perf_counter_ns() - start_t))
                            w_count = input_warn_counts.get(inp.input_id, 0)

                            # Determine factual per-input status
                            if len(request.inputs) > 1:
                                has_input_doc = inp.input_id in doc_map
                                has_input_artifact = (
                                    any(
                                        any(p.source_input_id == inp.input_id for p in art.provenance)
                                        for art in result.artifacts
                                    )
                                    if result.artifacts
                                    else False
                                )
                                has_output = has_input_doc or has_input_artifact
                            else:
                                has_output = (
                                    inp.input_id in doc_map
                                    or result.data is not None
                                    or bool(result.artifacts)
                                )

                            if not has_output:
                                f_stat = "FAILED"
                                failed_cnt += 1
                            elif w_count > 0:
                                f_stat = "WARNING"
                                warning_cnt += 1
                            else:
                                f_stat = "SUCCESS"
                                successful_cnt += 1

                            info = {
                                "input_id": inp.input_id,
                                "file_display_name": inp.display_name,
                                "status": f_stat,
                                "stage": "Completed",
                                "started_ns": start_t,
                                "duration_ns": duration,
                                "warning_count": w_count,
                            }
                            self._file_progress[inp.input_id] = info
                            self._file_progress[inp.display_name] = info

                        # Determine factual overall run status
                        if failed_cnt > 0 and successful_cnt == 0 and warning_cnt == 0:
                            overall_status = "FAILED"
                        elif failed_cnt > 0:
                            overall_status = "PARTIAL"
                        elif warning_cnt > 0:
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
                        )
                        self._terminal_status = overall_status
                        self._terminal_summary = summary
                except DoshError as dosh_err:
                    is_cancelled = (
                        (request.cancellation_token and request.cancellation_token.is_cancelled)
                        or bool(dosh_err.context.get("cancelled"))
                        or "cancelled" in dosh_err.message.lower()
                    )
                    status = "CANCELLED" if is_cancelled else "FAILED"
                    failures = (
                        ("Execution cancelled by user.",)
                        if is_cancelled
                        else (_format_public_error(dosh_err),)
                    )
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
                        self._terminal_status = status
                        self._terminal_summary = summary
                except Exception:
                    maruti_recs, pramana_recs = get_run_telemetry(self._agni, run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)
                    summary = MukhaPresenter.build_summary_view(
                        run_id=run_id,
                        status="FAILED",
                        wall_time_ns=wall_time_ns,
                        request=request,
                        result=None,
                        failures=("EXECUTION_FAILED: An internal error occurred during processing.",),
                        maruti_records=maruti_recs,
                        pramana_records=pramana_recs,
                    )
                    with self._lock:
                        self._terminal_status = "FAILED"
                        self._terminal_summary = summary
                finally:
                    with self._lock:
                        if self._terminal_summary is None:
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

            self._active_thread = threading.Thread(
                target=_worker,
                name=f"MukhaWorker-{run_id}",
                daemon=True,
            )
            self._active_thread.start()
            return StartRunResponse(status=StartRunStatus.OK, run_id=run_id)

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
                return True
            return False

    def reveal_output_directory(self, run_id: str) -> bool:
        """Safely reveal the confirmed run output folder in Windows Explorer / OS file manager in the foreground."""
        with self._lock:
            target_dir = self._run_output_roots.get(run_id)
        if target_dir is None or not target_dir.is_dir():
            return False

        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", str(target_dir)])
                try:
                    subprocess.run(
                        [
                            "powershell",
                            "-NoProfile",
                            "-Command",
                            "(New-Object -ComObject WScript.Shell).AppActivate('Explorer')",
                        ],
                        capture_output=True,
                        timeout=2.0,
                        check=False,
                    )
                except Exception:
                    pass
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
            return True
        except Exception:
            return False
