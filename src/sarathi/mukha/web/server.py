"""Mukha Local Web Server for Sarathi V2.

Implements a thin, loopback-bound ThreadingHTTPServer presenting canonical
Mukha view models, native Windows file picking, and executing runs via Agni.
"""

from __future__ import annotations

import importlib.resources
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    InputSelectionView,
    RunSummaryView,
    RunViewState,
)
from sarathi.mukha.web.native_picker import NativePicker
from sarathi.sankalpa import (
    CancellationToken,
    ExecutionProfile,
    Request,
    Result,
)

if TYPE_CHECKING:
    from sarathi.agni import Agni


def _serialize_dataclass(obj: Any) -> Any:
    """Safely and recursively serialize dataclass view models to JSON-friendly primitives."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize_dataclass(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_dataclass(v) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        result: dict[str, Any] = {}
        for field_name in obj.__dataclass_fields__:
            val = getattr(obj, field_name)
            result[field_name] = _serialize_dataclass(val)
        return result
    if hasattr(obj, "value"):  # Enums
        return obj.value
    return str(obj)


class MukhaHTTPHandler(BaseHTTPRequestHandler):
    """Loopback-only HTTP request handler for Mukha Web Frontend."""

    server: MukhaWebServer  # type: ignore[assignment]

    # Protocol defaults
    server_version = "SarathiMukha/2.0"
    MAX_BODY_SIZE = 1_048_576  # 1 MB

    @property
    def mukha_app(self) -> MukhaWebServer:
        """Access the parent MukhaWebServer instance safely."""
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
            self._send_json(413, {"ok": False, "error": "Request body exceeds size limit."})
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
            inputs, input_selection, preflight = MukhaPresenter.intake_from_paths(paths, recursive=recursive)
            self._send_json(
                200,
                {
                    "ok": True,
                    "input_selection": _serialize_dataclass(input_selection),
                    "preflight": _serialize_dataclass(preflight),
                },
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

            paths = [Path(p) for p in raw_paths if isinstance(p, str) and p.strip()]
            run_id = self.mukha_app.start_run(paths=paths, requirement=requirement, profile=prof, recursive=recursive)
            if run_id is None:
                self._send_json(
                    409,
                    {"ok": False, "error": "An interactive processing run is already active."},
                )
            else:
                self._send_json(200, {"ok": True, "run_id": run_id})
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
            # Fallback to local filesystem path
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

    def _serve_confirmed_artifact(self, run_id: str, artifact_name: str) -> None:
        """Stream confirmed artifact file safely from output root."""
        out_root = self.mukha_app.output_root
        if not out_root.is_dir():
            self.send_error(HTTPStatus.NOT_FOUND, "Output root unavailable.")
            return

        # Verify against traversal and ensure file exists under output root
        target_file = (out_root / artifact_name).resolve()
        try:
            target_file.relative_to(out_root.resolve())
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN, "Access to file outside output root is denied.")
            return

        if not target_file.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Confirmed artifact file not found on disk.")
            return

        mime_type, _ = mimetypes.guess_type(str(target_file))
        if mime_type is None:
            mime_type = "application/octet-stream"

        file_size = target_file.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(file_size))
        self.send_header("Content-Disposition", f'attachment; filename="{target_file.name}"')
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
        self._active_token: CancellationToken | None = None
        self._active_thread: threading.Thread | None = None
        self._active_start_ns: int = 0
        self._last_result: Result | None = None
        self._last_summary: RunSummaryView | None = None

    @property
    def output_root(self) -> Path:
        """Resolve current configured output root."""
        return self._agni.output_root

    @property
    def resolved_port(self) -> int:
        """Resolved TCP port the server is listening on."""
        return self._resolved_port

    @property
    def local_url(self) -> str:
        """Local URL to open in web browser."""
        return f"http://127.0.0.1:{self._resolved_port}/"

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

    def get_application_view_state(self) -> ApplicationViewState:
        """Build canonical typed ApplicationViewState projected from live facts."""
        with self._lock:
            active_run_id = self._active_run_id
            start_ns = self._active_start_ns
            last_result = self._last_result
            last_summary = self._last_summary

        active_run_view: RunViewState | None = None
        if active_run_id is not None:
            now_ns = time.perf_counter_ns()
            is_alive = self._active_thread is not None and self._active_thread.is_alive()
            status = "RUNNING" if is_alive else (last_result.status if last_result else "COMPLETED")

            maruti_recs = self._agni.darpana.maruti_records() if self._agni.darpana else ()
            pramana_recs = self._agni.darpana.pramana_records() if self._agni.darpana else ()

            active_run_view = MukhaPresenter.build_monitor_view(
                run_id=active_run_id,
                status=status,
                started_at_ns=start_ns,
                now_ns=now_ns,
                files=(),
                maruti_records=maruti_recs,
                pramana_records=pramana_recs,
            )

        # Capability availability
        available_actions = tuple(
            MukhaPresenter.build_home_view().available_actions
        )

        return ApplicationViewState(
            current_screen="monitor" if active_run_id and active_run_view and active_run_view.status == "RUNNING" else "home",
            requirement="read_native",
            policy_label="Local only",
            input_selection=InputSelectionView(total_files=0, total_size_bytes=0, is_grouped=False),
            active_run=active_run_view,
            terminal_summary=last_summary,
            available_actions=available_actions,
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

            # Intake and resolve input references
            inputs, input_selection, preflight = MukhaPresenter.intake_from_paths(paths, recursive=recursive)
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
            self._active_token = token
            self._active_start_ns = time.perf_counter_ns()
            self._last_result = None
            self._last_summary = None

            def _worker() -> None:
                try:
                    result = self._agni.execute(request)
                    maruti_recs = self._agni.darpana.maruti_records() if self._agni.darpana else ()
                    pramana_recs = self._agni.darpana.pramana_records() if self._agni.darpana else ()
                    wall_time_ns = max(0, time.perf_counter_ns() - self._active_start_ns)

                    summary = MukhaPresenter.build_summary_view(
                        run_id=run_id,
                        status=result.status,
                        wall_time_ns=wall_time_ns,
                        request=request,
                        result=result,
                        successful_files=len(inputs) if result.status == "SUCCESS" else 0,
                        warning_files=0,
                        failed_files=0 if result.status == "SUCCESS" else len(inputs),
                        maruti_records=maruti_recs,
                        pramana_records=pramana_recs,
                    )
                    with self._lock:
                        self._last_result = result
                        self._last_summary = summary
                except Exception as err:
                    with self._lock:
                        self._last_summary = RunSummaryView(
                            run_id=run_id,
                            status="FAILURE",
                            wall_time_ns=max(0, time.perf_counter_ns() - self._active_start_ns),
                            total_inputs=len(inputs),
                            failures=(str(err),),
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
        """Safely reveal the confirmed output folder in Windows Explorer / OS file manager."""
        out_dir = self.output_root
        if not out_dir.is_dir():
            return False

        try:
            if sys.platform == "win32":
                os.startfile(str(out_dir))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(out_dir)])
            else:
                subprocess.Popen(["xdg-open", str(out_dir)])
            return True
        except Exception:
            return False
