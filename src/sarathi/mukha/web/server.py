"""Mukha Local Web Server and HTTP Dispatcher for Sarathi V2.

Provides a thin, loopback-only (127.0.0.1) HTTP server that projects canonical
Sarathi presentation state (MukhaPresenter, Darpana, Kavacha, Nabhi) into a single
modern Web UI without external dependencies, frameworks, or cloud leaks.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.dosh import DoshError
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    AvailableActionView,
    FileRunView,
    InputItemView,
    InputSelectionView,
    InspectorViewState,
    RunSummaryView,
    RunViewState,
    WorkerPageView,
)
from sarathi.mukha.web.http_handler import (
    MukhaHTTPHandler,
    StartRunResponse,
    StartRunStatus,
    _format_public_error,
)
from sarathi.sankalpa import (
    ArtifactRef,
    CancellationToken,
    ExecutionProfile,
    Request,
    Result,
)

if TYPE_CHECKING:
    from sarathi.agni import Agni
    from sarathi.darpana import MarutiRecord, PramanaRecord


class MukhaWebServer:
    """Thin, loopback-only presentation server managing interactive Mukha web dashboard."""

    def __init__(
        self,
        agni: Agni,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        if host != "127.0.0.1":
            raise ValueError("MukhaWebServer strictly binds to 127.0.0.1 loopback only.")

        self._agni = agni
        self._host = host
        self._requested_port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._resolved_port: int = 0

        # Concurrency & Active Run state
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
    def agni(self) -> Any:
        """Resolve current Agni runtime composition root."""
        return self._agni

    @property
    def output_root(self) -> Path:
        """Resolve current configured output root."""
        return self._agni.output_root

    @property
    def runtime_root(self) -> Path:
        """Resolve current configured runtime root."""
        return self._agni.runtime_root

    @property
    def kavacha(self) -> Any:
        """Resolve current security service."""
        return self._agni.kavacha

    @property
    def registered_capabilities(self) -> tuple[str, ...]:
        """Return registered capabilities from Kosh."""
        return tuple(c.capability_id for c in self._agni.kosh.capabilities())

    @property
    def resolved_port(self) -> int:
        """Resolved TCP port the server is listening on."""
        return self._resolved_port

    @property
    def local_url(self) -> str:
        """Local URL to open in web browser."""
        return f"http://127.0.0.1:{self._resolved_port}/"

    def get_confirmed_artifact(self, run_id: str, artifact_id: str) -> ArtifactRef | None:
        """Look up confirmed ArtifactRef by run ID and artifact ID."""
        with self._lock:
            return self._confirmed_artifacts.get(run_id, {}).get(artifact_id)

    def get_run_history(self, limit: int = 50) -> tuple[Any, ...]:
        """Retrieve recent terminal run summaries from Darpana telemetry history."""
        if hasattr(self._agni, "darpana") and self._agni.darpana is not None:
            return self._agni.darpana.query_run_history(limit=limit)
        return ()

    def get_review_items(self, run_id: str | None = None) -> tuple[dict[str, Any], ...]:
        """Retrieve pending review/exception items from run result warnings."""
        with self._lock:
            res = self._last_result
        if res is None or not res.warnings:
            return ()
        items = []
        for idx, w in enumerate(res.warnings, start=1):
            items.append(
                {
                    "item_id": f"rev-{idx}",
                    "code": w.code,
                    "message": w.message,
                    "stage": w.stage,
                    "context": dict(w.context) if w.context else {},
                }
            )
        return tuple(items)

    def get_inspector_view(self, run_id: str) -> InspectorViewState | None:
        """Build InspectorViewState for the requested run ID from recorded facts."""
        with self._lock:
            is_active = self._active_run_id == run_id
            term_status = self._terminal_status
            is_alive = self._active_thread is not None and self._active_thread.is_alive()
            start_ns = self._active_start_ns if is_active else 0

        maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
        if not maruti_recs and not pramana_recs and not is_active:
            return None

        status = "RUNNING" if (is_active and is_alive) else (term_status or "COMPLETED")
        now_ns = time.perf_counter_ns()
        elapsed_ns = max(0, now_ns - start_ns) if start_ns > 0 else 0

        system_facts = (
            ("Loopback Host", self._host),
            ("Port", str(self._resolved_port)),
            ("Runtime Root", str(self.runtime_root)),
            ("Output Root", str(self.output_root)),
        )

        return MukhaPresenter.build_inspector_view(
            run_id=run_id,
            status=status,
            elapsed_ns=elapsed_ns,
            maruti_records=maruti_recs,
            pramana_records=pramana_recs,
            system_facts=system_facts,
        )

    def start(self) -> None:
        """Start the loopback web server on a background thread."""
        self._httpd = ThreadingHTTPServer((self._host, self._requested_port), MukhaHTTPHandler)
        self._httpd.mukha_server = self  # type: ignore[attr-defined]
        self._resolved_port = self._httpd.server_port

        self._server_thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="MukhaWebServerThread",
            daemon=True,
        )
        self._server_thread.start()

    def stop(self) -> None:
        """Cleanly shutdown the loopback web server."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

        if self._server_thread is not None and self._server_thread.is_alive():
            self._server_thread.join(timeout=2.0)
            self._server_thread = None

    def _get_run_telemetry(self, run_id: str) -> tuple[tuple[MarutiRecord, ...], tuple[PramanaRecord, ...]]:
        """Fetch telemetry records filtered strictly to the active run ID."""
        if not self._agni.darpana:
            return (), ()
        maruti = tuple(r for r in self._agni.darpana.maruti_records() if r.run_id == run_id or r.request_id == run_id)
        pramana = tuple(r for r in self._agni.darpana.pramana_records() if r.run_id == run_id or r.request_id == run_id)
        return maruti, pramana

    def get_application_view_state(self) -> ApplicationViewState:
        """Build canonical typed ApplicationViewState projected from live facts."""
        with self._lock:
            active_run_id = self._active_run_id
            active_req = self._active_request
            start_ns = self._active_start_ns
            last_summary = self._terminal_summary
            term_status = self._terminal_status
            is_alive = self._active_thread is not None and self._active_thread.is_alive()

        active_run_view: RunViewState | None = None
        if active_run_id is not None:
            now_ns = time.perf_counter_ns()
            status = "RUNNING" if is_alive else (term_status or "SUCCESS")
            maruti_recs, pramana_recs = self._get_run_telemetry(active_run_id)

            if active_req:
                req_decl = self._agni.kosh.get_capability(active_req.requirement)
                active_stage = req_decl.display_name if req_decl is not None else active_req.requirement
            else:
                active_stage = "Processing"


            with self._lock:
                live_prog = dict(self._live_progress)
                live_workers = dict(self._live_workers)
                file_prog_map = dict(self._file_progress)

            curr_page = live_prog.get("page_number")
            tot_pages = live_prog.get("total_pages")
            curr_file = live_prog.get("file_display_name")
            curr_input_id = live_prog.get("input_id")

            inputs = active_req.inputs if active_req else ()
            files_list = []
            for idx, inp in enumerate(inputs):
                f_prog = file_prog_map.get(inp.input_id) or file_prog_map.get(inp.display_name)
                is_curr = bool(
                    (curr_input_id and inp.input_id == curr_input_id)
                    or (curr_file and (inp.display_name == curr_file or inp.input_id == curr_file))
                )
                f_warn_count = f_prog.get("warning_count", 0) if f_prog else 0

                if is_alive:
                    if is_curr:
                        f_status = "RUNNING"
                        f_start = f_prog.get("started_ns", start_ns) if f_prog else start_ns
                        f_elapsed: int | None = max(0, now_ns - f_start)
                        if curr_page and tot_pages:
                            f_stage = f"{active_stage} (Page {curr_page}/{tot_pages})"
                        elif curr_page:
                            f_stage = f"{active_stage} (Page {curr_page})"
                        else:
                            f_stage = active_stage
                    elif f_prog:
                        f_status = f_prog.get("status", "SUCCESS")
                        f_stage = f_prog.get("stage", "Completed")
                        f_dur = f_prog.get("duration_ns")
                        if f_dur is not None:
                            f_elapsed = f_dur
                        else:
                            f_start = f_prog.get("started_ns", start_ns)
                            f_elapsed = max(0, f_prog.get("updated_ns", now_ns) - f_start)
                    else:
                        f_status = "PENDING"
                        f_stage = "Pending"
                        f_elapsed = None
                else:
                    if f_prog and f_prog.get("status"):
                        f_status = f_prog.get("status")
                        f_stage = f_prog.get("stage", "Completed")
                        f_elapsed = f_prog.get("duration_ns")
                    elif status in ("SUCCESS", "WARNING"):
                        f_status = "WARNING" if f_warn_count > 0 else "SUCCESS"
                        f_stage = "Completed"
                        f_elapsed = f_prog.get("duration_ns") if f_prog else None
                    elif status == "CANCELLED":
                        if f_prog and f_prog.get("status") in ("SUCCESS", "WARNING"):
                            f_status = f_prog.get("status")
                            f_stage = "Completed"
                            f_elapsed = f_prog.get("duration_ns")
                        else:
                            f_status = "CANCELLED"
                            f_stage = "Cancelled"
                            f_elapsed = None
                    else:
                        if f_prog and f_prog.get("status") in ("SUCCESS", "WARNING"):
                            f_status = f_prog.get("status")
                            f_stage = "Completed"
                            f_elapsed = f_prog.get("duration_ns")
                        else:
                            f_status = "FAILED"
                            f_stage = "Failed"
                            f_elapsed = None

                files_list.append(
                    FileRunView(
                        input_id=inp.input_id,
                        display_name=inp.display_name,
                        ordinal=idx + 1,
                        status=f_status,
                        elapsed_ns=f_elapsed,
                        current_stage=f_stage,
                        warning_count=f_warn_count,
                    )
                )
            files = tuple(files_list)

            if is_alive and inputs and live_workers:
                workers_list = []
                for wid, winfo in sorted(live_workers.items(), key=lambda kv: kv[0]):
                    w_start = winfo.get("started_ns", start_ns)
                    w_upd = winfo.get("updated_ns", start_ns)
                    workers_list.append(
                        WorkerPageView(
                            worker_id=str(wid),
                            file_display_name=winfo.get("file_display_name") or inputs[0].display_name,
                            page_number=winfo.get("page_number"),
                            stage=winfo.get("stage", active_stage),
                            device_type=winfo.get("device_type") or "",
                            elapsed_ns=max(0, now_ns - w_start),
                            idle_ns=max(0, now_ns - w_upd),
                            status="active",
                        )
                    )
                active_workers = tuple(workers_list)
            else:
                active_workers = ()

            active_run_view = MukhaPresenter.build_monitor_view(
                run_id=active_run_id,
                status=status,
                started_at_ns=start_ns,
                now_ns=now_ns,
                files=files,
                maruti_records=maruti_recs,
                pramana_records=pramana_recs,
                active_workers=active_workers,
            )

        # Capability availability facts
        caps_status = MukhaPresenter.audit_capability_status(agni=self._agni)
        registered_caps = set(self.registered_capabilities)

        available_actions = []
        for decl in self._agni.kosh.capabilities():
            act_id = decl.capability_id
            if act_id == "identify":
                continue  # internal classification stage, not an operator-triggered requirement
            act_label = decl.display_name

            is_avail, reason = caps_status.get(act_id, (False, "Unavailable"))
            enabled = is_avail and (act_id in registered_caps)
            disabled_reason = None if enabled else reason
            available_actions.append(
                AvailableActionView(
                    action_id=act_id,
                    label=act_label,
                    is_enabled=enabled,
                    disabled_reason=disabled_reason,
                )
            )

        if active_req:
            input_sel = InputSelectionView(
                total_files=len(active_req.inputs),
                total_size_bytes=sum(getattr(inp, "size_bytes", 0) or 0 for inp in active_req.inputs),
                is_grouped=False,
                items=tuple(
                    InputItemView(
                        input_id=inp.input_id,
                        display_name=inp.display_name,
                        size_bytes=getattr(inp, "size_bytes", 0) or 0,
                        media_type=inp.media_type,
                        source_path=str(inp.source_path) if inp.source_path else None,
                    )
                    for inp in active_req.inputs
                ),
            )
        else:
            input_sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)

        current_screen = "monitor" if active_run_id and is_alive else ("summary" if last_summary else "home")
        inspector_view = self.get_inspector_view(active_run_id) if active_run_id else None

        return ApplicationViewState(
            current_screen=current_screen,
            requirement=active_req.requirement if active_req else "read_native",
            policy_label="Local only",
            input_selection=input_sel,
            active_run=active_run_view,
            terminal_summary=last_summary,
            inspector=inspector_view,
            available_actions=tuple(available_actions),
        )

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
            return StartRunResponse(status=StartRunStatus.BUSY, error_message="An interactive processing run is already active.")

        # Intake and resolve input references outside lock
        inputs, input_selection, preflight = MukhaPresenter.intake_from_paths(
            paths,
            kavacha=self.kavacha,
            runtime_root=self.runtime_root,
            output_root=self.output_root,
            recursive=recursive,
        )
        if not inputs:
            return StartRunResponse(status=StartRunStatus.INVALID_INPUTS, error_message="No eligible input documents discovered.")

        with self._lock:
            if self._active_thread is not None and self._active_thread.is_alive():
                return StartRunResponse(status=StartRunStatus.BUSY, error_message="An interactive processing run is already active.")

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

            import uuid

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
                    maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
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
                        from sarathi.sankalpa import CanonicalDocument

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
                    maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
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
                    maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
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
                            maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
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
