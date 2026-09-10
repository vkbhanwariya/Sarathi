"""Mukha local web presentation façade backed by Starlette and Uvicorn."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import uvicorn

from sarathi.mukha.state import (
    ApplicationViewState,
    InspectorViewState,
    ReviewIntent,
    RunSummaryView,
)
from sarathi.mukha.web.app import create_mukha_app
from sarathi.mukha.web.runner import RunCoordinator, StartRunResponse
from sarathi.mukha.web.security import _format_public_error
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


class MukhaWebServer:
    """Loopback-only Starlette presentation server for the Mukha web application."""

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
        self._resolved_port = 0
        self._runner = RunCoordinator(agni)
        self._asgi_app = create_mukha_app(self)
        self._uvicorn_server: uvicorn.Server | None = None
        self._server_thread: threading.Thread | None = None
        self._server_socket: socket.socket | None = None

    @property
    def runner(self) -> RunCoordinator:
        """Return the interactive run coordinator."""
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
        """Return True when an interactive processing run is active."""
        return self._runner.is_busy()

    @property
    def agni(self) -> Any:
        """Return the current Agni composition root."""
        return self._agni

    @property
    def output_root(self) -> Path:
        """Return the configured output root."""
        return self._agni.output_root

    @property
    def runtime_root(self) -> Path:
        """Return the configured runtime root."""
        return self._agni.runtime_root

    @property
    def kavacha(self) -> Any:
        """Return the current security service."""
        return self._agni.kavacha

    @property
    def registered_capabilities(self) -> tuple[str, ...]:
        """Return capability IDs registered in Kosh."""
        return tuple(capability.capability_id for capability in self._agni.kosh.capabilities())

    @property
    def resolved_port(self) -> int:
        """Return the TCP port currently used by the local server."""
        return self._resolved_port

    @property
    def local_url(self) -> str:
        """Return the canonical loopback origin for the Mukha application."""
        return f"http://127.0.0.1:{self._resolved_port}"

    def get_confirmed_artifact(self, run_id: str, artifact_id: str) -> ArtifactRef | None:
        """Look up a confirmed artifact by run and artifact IDs."""
        return self._runner.get_confirmed_artifact(run_id, artifact_id)

    def get_input_path(self, input_id: str) -> Path | None:
        """Look up an authorized input source path by input ID."""
        return self._runner.get_input_path(input_id)

    def get_run_summary(self, run_id: str) -> Any | None:
        """Return a terminal run summary, including persisted Darpana history."""
        summary = self._runner.get_run_summary(run_id)
        if summary is not None:
            return summary
        if hasattr(self._agni, "darpana") and self._agni.darpana is not None:
            terminal = self._agni.darpana.get_run_summary(run_id)
            if terminal is not None:
                status = terminal.status.upper()
                if status == "COMPLETED":
                    status = "SUCCESS"
                total_inputs = max(1, terminal.artifact_count) if status == "SUCCESS" else terminal.artifact_count
                successful_files = terminal.artifact_count if status == "SUCCESS" else 0
                failed_files = 1 if status == "FAILED" else 0
                return RunSummaryView(
                    run_id=terminal.run_id,
                    status=status,
                    wall_time_ns=terminal.duration_ms * 1_000_000,
                    total_inputs=total_inputs,
                    successful_files=successful_files,
                    warning_files=terminal.warning_count,
                    failed_files=failed_files,
                    quarantined_count=0,
                    retry_count=0,
                    warnings=(
                        tuple(f"Execution warning {index + 1}" for index in range(terminal.warning_count))
                        if terminal.warning_count
                        else ()
                    ),
                    failures=("Execution failed." if status == "FAILED" else ()),
                )
        return None

    def get_run_history(self, limit: int = 50) -> tuple[Any, ...]:
        """Return recent terminal run summaries from Darpana history."""
        return query_run_history(self._agni, limit=limit)

    def clear_history(self) -> bool:
        """Clear coordinator and Darpana run history."""
        self._runner.clear_history()
        if hasattr(self._agni, "darpana") and self._agni.darpana is not None:
            return self._agni.darpana.clear_history()
        return True

    def clear_cache(self) -> int:
        """Clear the two-tier Smriti result cache."""
        if hasattr(self._agni, "smriti") and self._agni.smriti is not None:
            return self._agni.smriti.clear()
        return 0

    def get_review_items(self, run_id: str | None = None) -> tuple[dict[str, Any], ...]:
        """Return pending review/exception items."""
        return extract_review_items(self._runner, run_id=run_id)

    def apply_review_intent(self, intent: ReviewIntent) -> bool:
        """Apply one validated human review decision."""
        return self._runner.apply_review_intent(intent)

    def get_inspector_view(self, run_id: str) -> InspectorViewState | None:
        """Build the inspector view for one run."""
        return build_inspector_view(
            self._agni,
            self._runner,
            run_id,
            self._host,
            self._resolved_port,
        )

    def get_application_view_state(self) -> ApplicationViewState:
        """Build the canonical application presentation state."""
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
        """Start a document-processing run through the run coordinator."""
        return self._runner.start_run(
            paths=paths,
            requirement=requirement,
            profile=profile,
            recursive=recursive,
            custom_options=custom_options,
        )

    def cancel_run(self, run_id: str) -> bool:
        """Cooperatively cancel the active run when IDs match."""
        return self._runner.cancel_run(run_id)

    def reveal_output_directory(self, run_id: str) -> bool:
        """Reveal the confirmed run output directory in the OS file manager."""
        return self._runner.reveal_output_directory(run_id)

    def start(self) -> None:
        """Start Uvicorn on a pre-bound loopback socket in a daemon thread."""
        if self._server_thread is not None and self._server_thread.is_alive():
            return

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self._host, self._requested_port))
        server_socket.listen(128)
        server_socket.setblocking(False)
        self._resolved_port = int(server_socket.getsockname()[1])

        config = uvicorn.Config(
            self._asgi_app,
            host=self._host,
            port=self._resolved_port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        self._uvicorn_server = server
        self._server_socket = server_socket
        self._server_thread = threading.Thread(
            target=server.run,
            kwargs={"sockets": [server_socket]},
            name="MukhaWebServerThread",
            daemon=True,
        )
        self._server_thread.start()

        deadline = time.monotonic() + 5.0
        while not server.started:
            if not self._server_thread.is_alive():
                self.stop()
                raise RuntimeError("Mukha web server failed to start.")
            if time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("Mukha web server startup timed out.")
            time.sleep(0.01)

    def stop(self) -> None:
        """Stop Uvicorn and release the loopback socket cleanly."""
        server = self._uvicorn_server
        thread = self._server_thread
        if server is not None:
            server.should_exit = True

        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
            if thread.is_alive() and server is not None:
                server.force_exit = True
                thread.join(timeout=1.0)

        sock = self._server_socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

        self._uvicorn_server = None
        self._server_thread = None
        self._server_socket = None


__all__ = ["MukhaWebServer", "_format_public_error"]
