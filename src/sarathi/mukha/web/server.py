"""Mukha Local Web Server and Presentation Façade for Sarathi V2.

Provides a thin, loopback-only (127.0.0.1) HTTP server that projects canonical
Sarathi presentation state (MukhaPresenter, Darpana, Kavacha, Nabhi) into a single
modern Web UI without external dependencies, frameworks, or cloud leaks.
"""

from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.mukha.state import (
    ApplicationViewState,
    InspectorViewState,
    ReviewIntent,
    RunSummaryView,
)
from sarathi.mukha.web.http_handler import (
    MukhaHTTPHandler,
    StartRunResponse,
    _format_public_error,
)
from sarathi.mukha.web.runner import RunCoordinator
from sarathi.mukha.web.state_builder import (
    build_application_view_state,
    build_inspector_view,
    extract_review_items,
    get_run_telemetry,
    query_run_history,
)
from sarathi.sankalpa import ArtifactRef, ExecutionProfile

if TYPE_CHECKING:
    from sarathi.agni import Agni
    from sarathi.darpana import MarutiRecord, PramanaRecord


class _MukhaHTTPServer(ThreadingHTTPServer):
    """Loopback ThreadingHTTPServer that gracefully ignores routine client aborts and resets."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc_type, _, _ = sys.exc_info()
        if exc_type is not None and issubclass(
            exc_type, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)
        ):
            # Client disconnected or closed socket before server finished reading/writing (browser navigation/refresh)
            return
        super().handle_error(request, client_address)

    def serve_forever(self, poll_interval: float = 0.05) -> None:
        """Serve requests continuously with 50ms polling interval for rapid teardown."""
        super().serve_forever(poll_interval=poll_interval)


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

        # Delegate execution and run state to RunCoordinator
        self._runner = RunCoordinator(agni)

    @property
    def runner(self) -> RunCoordinator:
        """Access internal run coordinator."""
        return self._runner

    @property
    def _lock(self) -> threading.Lock:
        """Backward-compatible access to runner synchronization lock."""
        return self._runner._lock

    @property
    def _confirmed_artifacts(self) -> dict[str, dict[str, ArtifactRef]]:
        """Backward-compatible access to confirmed artifacts map."""
        return self._runner._confirmed_artifacts

    @_confirmed_artifacts.setter
    def _confirmed_artifacts(self, val: dict[str, dict[str, ArtifactRef]]) -> None:
        self._runner._confirmed_artifacts = val

    @property
    def _run_output_roots(self) -> dict[str, Path]:
        """Backward-compatible access to run output roots map."""
        return self._runner._run_output_roots

    @_run_output_roots.setter
    def _run_output_roots(self, val: dict[str, Path]) -> None:
        self._runner._run_output_roots = val

    def _get_run_telemetry(self, run_id: str) -> tuple[tuple[MarutiRecord, ...], tuple[PramanaRecord, ...]]:
        """Backward-compatible run-filtered telemetry query helper."""
        return get_run_telemetry(self._agni, run_id)

    def is_busy(self) -> bool:
        """Return True if an interactive processing run is currently active on background worker thread."""
        return self._runner.is_busy()

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
        return self._runner.get_confirmed_artifact(run_id, artifact_id)

    def get_input_path(self, input_id: str) -> Path | None:
        """Look up source file Path for an input ID from active or cached intake inputs."""
        return self._runner.get_input_path(input_id)

    def get_run_summary(self, run_id: str) -> Any | None:
        """Look up full terminal run summary by run ID, falling back to Darpana persistence."""
        summary = self._runner.get_run_summary(run_id)
        if summary is not None:
            return summary
        if hasattr(self._agni, "darpana") and self._agni.darpana is not None:
            term_summary = self._agni.darpana.get_run_summary(run_id)
            if term_summary is not None:
                stat = term_summary.status.upper()
                if stat == "COMPLETED":
                    stat = "SUCCESS"
                total_in = max(1, term_summary.artifact_count) if stat == "SUCCESS" else term_summary.artifact_count
                succ_files = term_summary.artifact_count if stat == "SUCCESS" else 0
                fail_files = 1 if stat == "FAILED" else 0
                return RunSummaryView(
                    run_id=term_summary.run_id,
                    status=stat,
                    wall_time_ns=term_summary.duration_ms * 1_000_000,
                    total_inputs=total_in,
                    successful_files=succ_files,
                    warning_files=term_summary.warning_count,
                    failed_files=fail_files,
                    quarantined_count=0,
                    retry_count=0,
                    warnings=tuple(f"Execution warning {i+1}" for i in range(term_summary.warning_count)) if term_summary.warning_count else (),
                    failures=("Execution failed." if stat == "FAILED" else ()),
                )
        return None

    def get_run_history(self, limit: int = 50) -> tuple[Any, ...]:
        """Retrieve recent terminal run summaries from Darpana telemetry history."""
        return query_run_history(self._agni, limit=limit)

    def clear_history(self) -> bool:
        """Clear run history in coordinator and Darpana telemetry store."""
        self._runner.clear_history()
        if hasattr(self._agni, "darpana") and self._agni.darpana is not None:
            return self._agni.darpana.clear_history()
        return True

    def clear_cache(self) -> int:
        """Clear two-tier Smriti cache (L1 memory and L2 SQLite store)."""
        if hasattr(self._agni, "smriti") and self._agni.smriti is not None:
            return self._agni.smriti.clear()
        return 0


    def get_review_items(self, run_id: str | None = None) -> tuple[dict[str, Any], ...]:
        """Retrieve pending review/exception items from run result warnings."""
        return extract_review_items(self._runner, run_id=run_id)

    def apply_review_intent(self, intent: ReviewIntent) -> bool:
        """Apply a human review decision to the coordinator."""
        return self._runner.apply_review_intent(intent)

    def get_inspector_view(self, run_id: str) -> InspectorViewState | None:
        """Build InspectorViewState for the requested run ID from recorded facts."""
        return build_inspector_view(
            self._agni,
            self._runner,
            run_id,
            self._host,
            self._resolved_port,
        )

    def get_application_view_state(self) -> ApplicationViewState:
        """Build canonical typed ApplicationViewState projected from live facts."""
        return build_application_view_state(
            self._agni,
            self._runner,
            self._host,
            self._resolved_port,
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
        return self._runner.start_run(
            paths=paths,
            requirement=requirement,
            profile=profile,
            recursive=recursive,
            custom_options=custom_options,
        )

    def cancel_run(self, run_id: str) -> bool:
        """Cooperatively signal cancellation for the active run."""
        return self._runner.cancel_run(run_id)

    def reveal_output_directory(self, run_id: str) -> bool:
        """Safely reveal the confirmed run output folder in Windows Explorer / OS file manager in the foreground."""
        return self._runner.reveal_output_directory(run_id)

    def start(self) -> None:
        """Start the loopback web server on a background thread."""
        self._httpd = _MukhaHTTPServer((self._host, self._requested_port), MukhaHTTPHandler)
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


__all__ = ["MukhaWebServer", "_format_public_error"]
