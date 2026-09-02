"""Mukha Local Web Server and HTTP Dispatcher for Sarathi V2.

Provides a thin, loopback-only (127.0.0.1) HTTP server that projects canonical
Sarathi presentation state (MukhaPresenter, Darpana, Kavacha, Nabhi) into a single
modern Web UI without external dependencies, frameworks, or cloud leaks.
"""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.resources
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Any
import urllib.parse

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    AvailableActionView,
    FileRunView,
    InputItemView,
    InputSelectionView,
    RunSummaryView,
    RunViewState,
)
from sarathi.mukha.web.native_picker import NativePicker
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


def _serialize_dataclass(obj: Any) -> Any:
    """Recursively convert dataclasses and enums into JSON-serializable primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if hasattr(obj, "value"):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        res = {}
        for k in obj.__dataclass_fields__:
            val = getattr(obj, k)
            res[k] = _serialize_dataclass(val)
        return res
    if isinstance(obj, (list, tuple)):
        return [_serialize_dataclass(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_dataclass(v) for k, v in obj.items()}
    return str(obj)


class MukhaHTTPHandler(BaseHTTPRequestHandler):
    """Loopback-only HTTP request handler for the Mukha Web UI."""

    # Maximum payload size: 1 MB
    MAX_BODY_SIZE = 1_048_576

    @property
    def mukha_app(self) -> MukhaWebServer:
        """Resolve the parent MukhaWebServer instance attached to the socket server."""
        return getattr(self.server, "mukha_server", self.server)  # type: ignore[no-any-return]

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stdout access logging to keep terminal clean."""
        return

    def _drain_body(self) -> None:
        """Drain request body if present to ensure clean TCP response."""
        try:
            length_str = self.headers.get("Content-Length")
            if length_str:
                length = min(int(length_str), 65536)
                if length > 0:
                    self.rfile.read(length)
        except Exception:
            pass

    def _validate_host_and_origin(self) -> bool:
        """Validate Host and Origin headers to enforce strict loopback security."""
        host = self.headers.get("Host", "")
        if not host.startswith(("127.0.0.1", "localhost")):
            self._drain_body()
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Forbidden Host header."})
            return False

        origin = self.headers.get("Origin")
        if origin is not None:
            parsed = urllib.parse.urlparse(origin)
            if parsed.hostname not in ("127.0.0.1", "localhost"):
                self._drain_body()
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Forbidden Origin header."})
                return False
        return True

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        """Send a structured JSON response."""
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except Exception:
            body = b'{"ok":false,"error":"Serialization error."}'
            status = 500

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any] | None:
        """Read and parse JSON request body with strict size checks."""
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            return {}

        try:
            length = int(content_length_str)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Invalid Content-Length header."})
            return None

        if length > self.MAX_BODY_SIZE:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "Request body exceeds size limit."})
            return None

        raw_body = self.rfile.read(length)
        if not raw_body:
            return {}

        try:
            parsed = json.loads(raw_body.decode("utf-8"))
            if not isinstance(parsed, dict):
                self._send_json(400, {"ok": False, "error": "JSON body must be an object."})
                return None
            return parsed
        except Exception:
            self._send_json(400, {"ok": False, "error": "Malformed JSON payload."})
            return None

    def do_GET(self) -> None:
        """Serve static web assets, presentation state, and confirmed artifacts."""
        if not self._validate_host_and_origin():
            return

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Root and Static Assets
        if path in ("/", "/index.html"):
            self._serve_static_resource("app.html", "text/html; charset=utf-8")
            return
        elif path == "/app.css":
            self._serve_static_resource("app.css", "text/css; charset=utf-8")
            return
        elif path == "/app.js":
            self._serve_static_resource("app.js", "application/javascript; charset=utf-8")
            return

        # 2. GET /api/state
        elif path == "/api/state":
            app_state = self.mukha_app.get_application_view_state()
            self._send_json(200, {"ok": True, "state": _serialize_dataclass(app_state)})
            return

        # 3. GET /api/runs/<run_id>/artifacts/<artifact_id>
        elif path.startswith("/api/runs/") and "/artifacts/" in path:
            parts = path.strip("/").split("/")
            if len(parts) == 5 and parts[1] == "runs" and parts[3] == "artifacts":
                run_id = parts[2]
                artifact_id = urllib.parse.unquote(parts[4])
                self._serve_confirmed_artifact(run_id, artifact_id)
                return

        self.send_error(HTTPStatus.NOT_FOUND, "Resource not found.")

    def do_POST(self) -> None:
        """Handle typed browser actions (browse, intake, runs, cancel, reveal)."""
        if not self._validate_host_and_origin():
            return

        body = self._read_json_body()
        if body is None:
            return

        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. POST /api/browse/files
        if path == "/api/browse/files":
            result = NativePicker.browse_files()
            if not result.is_available:
                self._send_json(200, {"ok": False, "error": result.error_message})
            else:
                self._send_json(200, {"ok": True, "paths": list(result.paths)})
            return

        # 2. POST /api/browse/folder
        elif path == "/api/browse/folder":
            result = NativePicker.browse_folder()
            if not result.is_available:
                self._send_json(200, {"ok": False, "error": result.error_message})
            else:
                self._send_json(200, {"ok": True, "paths": list(result.paths)})
            return

        # 3. POST /api/intake
        elif path == "/api/intake":
            raw_paths = body.get("paths", [])
            recursive = bool(body.get("recursive", True))
            if not isinstance(raw_paths, list):
                self._send_json(400, {"ok": False, "error": "'paths' must be a list."})
                return

            paths = [Path(p) for p in raw_paths if isinstance(p, str) and p.strip()]
            try:
                inputs, input_selection, preflight = MukhaPresenter.intake_from_paths(
                    paths,
                    kavacha=self.mukha_app.kavacha,
                    runtime_root=self.mukha_app.runtime_root,
                    output_root=self.mukha_app.output_root,
                    recursive=recursive,
                )
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "input_selection": _serialize_dataclass(input_selection),
                        "preflight": _serialize_dataclass(preflight),
                    },
                )
            except DoshError as dosh_err:
                self._send_json(
                    403 if dosh_err.code is FailureCode.SECURITY_DENIED else 400,
                    {"ok": False, "error": f"{dosh_err.code.name}: {dosh_err.message}"},
                )
            return

        # 4. POST /api/runs
        elif path == "/api/runs":
            raw_paths = body.get("paths", [])
            requirement = body.get("requirement", "read_native")
            profile_str = body.get("profile", "instant")
            recursive = bool(body.get("recursive", True))

            if not isinstance(raw_paths, list) or not raw_paths:
                self._send_json(400, {"ok": False, "error": "No input paths provided."})
                return

            try:
                prof = ExecutionProfile.from_string(profile_str)
            except ValueError:
                self._send_json(400, {"ok": False, "error": f"Invalid profile: {profile_str}"})
                return

            # Validate requirement availability before dispatching
            caps_status = MukhaPresenter.audit_capability_status()
            registered_caps = set(self.mukha_app.registered_capabilities)
            is_avail, reason = caps_status.get(requirement, (False, "Capability unavailable."))
            if not is_avail or requirement not in registered_caps:
                self._send_json(
                    400,
                    {"ok": False, "error": f"Selected requirement '{requirement}' is unavailable: {reason}"},
                )
                return

            paths = [Path(p) for p in raw_paths if isinstance(p, str) and p.strip()]
            try:
                run_id = self.mukha_app.start_run(paths=paths, requirement=requirement, profile=prof, recursive=recursive)
                if run_id is None:
                    self._send_json(
                        409,
                        {"ok": False, "error": "An interactive processing run is already active."},
                    )
                else:
                    self._send_json(200, {"ok": True, "run_id": run_id})
            except DoshError as dosh_err:
                self._send_json(
                    403 if dosh_err.code is FailureCode.SECURITY_DENIED else 400,
                    {"ok": False, "error": f"{dosh_err.code.name}: {dosh_err.message}"},
                )
            return

        # 5. POST /api/runs/<run_id>/cancel
        elif path.startswith("/api/runs/") and path.endswith("/cancel"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                run_id = parts[2]
                cancelled = self.mukha_app.cancel_run(run_id)
                self._send_json(200, {"ok": True, "cancelled": cancelled})
                return

        # 6. POST /api/runs/<run_id>/reveal
        elif path.startswith("/api/runs/") and path.endswith("/reveal"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                run_id = parts[2]
                revealed = self.mukha_app.reveal_output_directory(run_id)
                self._send_json(200, {"ok": True, "revealed": revealed})
                return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found.")

    def _serve_static_resource(self, filename: str, content_type: str) -> None:
        """Serve packaged static asset using importlib.resources."""
        try:
            pkg = importlib.resources.files("sarathi.mukha.web")
            resource = pkg.joinpath(filename)
            content = resource.read_bytes()
        except Exception:
            local_path = Path(__file__).parent / filename
            if not local_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"Static resource {filename} missing.")
                return
            content = local_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def _serve_confirmed_artifact(self, run_id: str, artifact_id: str) -> None:
        """Stream confirmed artifact file safely by resolving run_id and artifact_id."""
        art_ref = self.mukha_app.get_confirmed_artifact(run_id, artifact_id)
        if art_ref is None or not art_ref.path or not art_ref.path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Confirmed artifact not found.")
            return

        target_file = art_ref.path.resolve()

        # Strict containment validation
        out_root = self.mukha_app.output_root.resolve()
        runtime_root = self.mukha_app.runtime_root.resolve()
        try:
            target_file.relative_to(out_root)
        except ValueError:
            try:
                target_file.relative_to(runtime_root)
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN, "Access to file outside authorized roots is denied.")
                return

        mime_type = art_ref.media_type or mimetypes.guess_type(str(target_file))[0] or "application/octet-stream"
        file_size = target_file.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Content-Disposition", f'attachment; filename="{target_file.name}"')
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()

        with open(target_file, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)


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
        maruti = tuple(r for r in self._agni.darpana.maruti_records() if r.run_id == run_id)
        pramana = tuple(r for r in self._agni.darpana.pramana_records() if r.run_id == run_id)
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

            inputs = active_req.inputs if active_req else ()
            files = tuple(
                FileRunView(
                    input_id=inp.input_id,
                    display_name=inp.display_name,
                    ordinal=idx + 1,
                    status=status,
                    elapsed_ns=max(0, now_ns - start_ns),
                    current_stage="Processing" if is_alive else "Completed",
                )
                for idx, inp in enumerate(inputs)
            )

            active_run_view = MukhaPresenter.build_monitor_view(
                run_id=active_run_id,
                status=status,
                started_at_ns=start_ns,
                now_ns=now_ns,
                files=files,
                maruti_records=maruti_recs,
                pramana_records=pramana_recs,
            )

        # Capability availability facts
        caps_status = MukhaPresenter.audit_capability_status()
        registered_caps = set(self.registered_capabilities)

        action_specs = [
            ("read_native", "Native Extraction"),
            ("bank_statements", "Bank Statements"),
            ("ocr", "Optical Character Recognition (OCR)"),
            ("font_conversion", "Font Conversion (Kruti Dev)"),
            ("translation", "Language Translation"),
        ]

        available_actions = []
        for act_id, act_label in action_specs:
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
                total_size_bytes=sum(inp.size_bytes for inp in active_req.inputs),
                is_grouped=False,
                items=tuple(
                    InputItemView(
                        input_id=inp.input_id,
                        display_name=inp.display_name,
                        size_bytes=inp.size_bytes,
                        media_type=inp.media_type,
                    )
                    for inp in active_req.inputs
                ),
            )
        else:
            input_sel = InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False)

        current_screen = "monitor" if active_run_id and is_alive else ("summary" if last_summary else "home")

        return ApplicationViewState(
            current_screen=current_screen,
            requirement=active_req.requirement if active_req else "read_native",
            policy_label="Local only",
            input_selection=input_sel,
            active_run=active_run_view,
            terminal_summary=last_summary,
            available_actions=tuple(available_actions),
        )

    def start_run(
        self,
        paths: list[Path],
        requirement: str = "read_native",
        profile: ExecutionProfile = ExecutionProfile.INSTANT,
        recursive: bool = True,
    ) -> str | None:
        """Start a document processing run on a background worker thread.

        Enforces single interactive run concurrency. Returns run_id if started, None if busy.
        """
        with self._lock:
            if self._active_thread is not None and self._active_thread.is_alive():
                return None  # Busy

            # Intake and resolve input references with full canonical security checks
            inputs, input_selection, preflight = MukhaPresenter.intake_from_paths(
                paths,
                kavacha=self.kavacha,
                runtime_root=self.runtime_root,
                output_root=self.output_root,
                recursive=recursive,
            )
            if not inputs:
                return None

            import uuid

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            token = CancellationToken()
            request = Request(
                request_id=run_id,
                requirement=requirement,
                inputs=inputs,
                profile=profile,
                cancellation_token=token,
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
                        self._terminal_status = "SUCCESS"
                        if run_id not in self._confirmed_artifacts:
                            self._confirmed_artifacts[run_id] = {}
                        for art in result.artifacts:
                            if isinstance(art, ArtifactRef):
                                self._confirmed_artifacts[run_id][art.artifact_id] = art
                                if art.path and art.path.parent.exists():
                                    self._run_output_roots[run_id] = art.path.parent

                        summary = MukhaPresenter.build_summary_view(
                            run_id=run_id,
                            status="SUCCESS",
                            wall_time_ns=wall_time_ns,
                            request=request,
                            result=result,
                            successful_files=None,
                            warning_files=None,
                            failed_files=None,
                            maruti_records=maruti_recs,
                            pramana_records=pramana_recs,
                        )
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
                        else (f"{dosh_err.code.name}: {dosh_err.message}",)
                    )
                    maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)
                    with self._lock:
                        self._terminal_status = status
                        self._terminal_summary = RunSummaryView(
                            run_id=run_id,
                            status=status,
                            wall_time_ns=wall_time_ns,
                            total_inputs=len(request.inputs),
                            failures=failures,
                            stage_timings=(),
                            device_summaries=(),
                            artifacts=(),
                        )
                except Exception:
                    maruti_recs, pramana_recs = self._get_run_telemetry(run_id)
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)
                    with self._lock:
                        self._terminal_status = "FAILED"
                        self._terminal_summary = RunSummaryView(
                            run_id=run_id,
                            status="FAILED",
                            wall_time_ns=wall_time_ns,
                            total_inputs=len(request.inputs),
                            failures=("EXECUTION_FAILED: An unexpected error occurred during execution.",),
                            stage_timings=(),
                            device_summaries=(),
                            artifacts=(),
                        )

            self._active_thread = threading.Thread(
                target=_worker,
                name=f"MukhaWorker-{run_id}",
                daemon=True,
            )
            self._active_thread.start()
            return run_id

    def cancel_run(self, run_id: str) -> bool:
        """Cooperatively signal cancellation for the active run."""
        with self._lock:
            if self._active_run_id == run_id and self._active_token is not None:
                self._active_token.cancel()
                return True
            return False

    def reveal_output_directory(self, run_id: str) -> bool:
        """Safely reveal the confirmed run output folder in Windows Explorer / OS file manager."""
        with self._lock:
            target_dir = self._run_output_roots.get(run_id)
        if target_dir is None or not target_dir.is_dir():
            return False

        try:
            if sys.platform == "win32":
                os.startfile(str(target_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target_dir)])
            else:
                subprocess.Popen(["xdg-open", str(target_dir)])
            return True
        except Exception:
            return False
