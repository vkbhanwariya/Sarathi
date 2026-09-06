"""Mukha Local Web Server HTTP Request Handler for Sarathi V2.

Provides loopback-only (127.0.0.1) HTTP request dispatching, security header enforcement,
host/origin validation, native file picker execution, and confirmed artifact streaming.
"""

from __future__ import annotations

import importlib.resources
import json
import mimetypes
import re
import urllib.parse
from dataclasses import dataclass
from enum import Enum, StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.web.native_picker import NativePicker
from sarathi.sankalpa import ExecutionProfile

if TYPE_CHECKING:
    from sarathi.mukha.web.server import MukhaWebServer


_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Path sanitization patterns for error messages: quoted paths, UNC paths, Windows drive paths, Unix paths
_QUOTED_PATH_PATTERN = re.compile(r"""(?P<q>['"])(?:[A-Za-z]:[\\/]|\\\\|/)[^'"]*(?P=q)""")
_UNC_PATH_PATTERN = re.compile(r"""\\\\[a-zA-Z0-9._-]+\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\s\\/:*?"<>|\r\n,;]*""")
_WIN_PATH_PATTERN = re.compile(r"""[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\s\\/:*?"<>|\r\n,;]*""")
_UNIX_PATH_PATTERN = re.compile(r"""(?:^|(?<=[\s(]))/(?:[^/\s'"()<>\r\n,;]+/+)*[^/\s'"()<>\r\n,;]+""")


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


def _sanitize_message(msg: str) -> str:
    """Sanitize error messages to eliminate raw filesystem paths, UNC paths, and quotes."""
    if not msg:
        return ""
    res = _QUOTED_PATH_PATTERN.sub("[path]", msg)
    res = _UNC_PATH_PATTERN.sub("[path]", res)
    res = _WIN_PATH_PATTERN.sub("[path]", res)
    res = _UNIX_PATH_PATTERN.sub("[path]", res)
    return " ".join(res.split())


def _format_public_error(dosh_err: DoshError) -> str:
    """Format public DoshError for web presentation without leaking paths or secrets."""
    sanitized = _sanitize_message(dosh_err.message)
    if sanitized:
        return f"{dosh_err.code.name}: {sanitized}"
    return dosh_err.code.name


def _serialize_dataclass(obj: Any) -> Any:
    """Recursively convert dataclasses and enums into JSON-serializable primitives."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Enum):
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


_ALLOWED_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_authorized_loopback_host(host_header: str) -> bool:
    """Structurally parse and validate Host header against approved loopback endpoints."""
    if not host_header or not isinstance(host_header, str):
        return False
    clean = host_header.strip()
    if not clean:
        return False

    # Handle bracketed IPv6: [::1] or [::1]:port
    if clean.startswith("["):
        closing = clean.find("]")
        if closing == -1:
            return False
        hostname = clean[1:closing]
        port_part = clean[closing + 1 :]
        if port_part:
            if not port_part.startswith(":"):
                return False
            port_str = port_part[1:]
            try:
                port = int(port_str)
                if not (1 <= port <= 65535):
                    return False
            except ValueError:
                return False
        return hostname.lower() in _ALLOWED_LOOPBACK_HOSTNAMES

    # Handle standard host[:port]
    if ":" in clean:
        parts = clean.split(":")
        if len(parts) != 2:
            return False
        hostname, port_str = parts[0], parts[1]
        try:
            port = int(port_str)
            if not (1 <= port <= 65535):
                return False
        except ValueError:
            return False
    else:
        hostname = clean

    return hostname.lower() in _ALLOWED_LOOPBACK_HOSTNAMES


def _is_authorized_loopback_origin(origin_header: str) -> bool:
    """Structurally validate Origin header against approved loopback endpoints."""
    if not origin_header or not isinstance(origin_header, str):
        return False
    try:
        parsed = urllib.parse.urlparse(origin_header)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.hostname is None or parsed.hostname.lower() not in _ALLOWED_LOOPBACK_HOSTNAMES:
            return False
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return False
    except (ValueError, TypeError):
        return False
    return True


class MukhaHTTPHandler(BaseHTTPRequestHandler):
    """Loopback-only HTTP request handler for the interactive Mukha presentation server."""

    MAX_BODY_SIZE: int = 1_048_576  # 1 MB strict limit
    _SECURITY_CSP: str = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )

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
                raw_len = int(length_str)
                if raw_len > 0:
                    length = min(raw_len, 65536)
                    self.rfile.read(length)
        except Exception:
            pass

    def _validate_host_and_origin(self) -> bool:
        """Validate Host and Origin headers to enforce strict loopback security."""
        host = self.headers.get("Host", "")
        if not _is_authorized_loopback_host(host):
            self._drain_body()
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Forbidden Host header."})
            return False

        origin = self.headers.get("Origin")
        if origin is not None and not _is_authorized_loopback_origin(origin):
            self._drain_body()
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Forbidden Origin header."})
            return False
        return True

    def _apply_security_headers(self, cache_control: str = "no-store") -> None:
        """Apply centralized response security and caching headers."""
        self.send_header("Content-Security-Policy", self._SECURITY_CSP)
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", cache_control)

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
        self._apply_security_headers(cache_control="no-store")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _read_json_body(self) -> dict[str, Any] | None:
        """Read and parse JSON request body with strict size checks."""
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            return {}

        try:
            length = int(content_length_str)
            if length < 0:
                raise ValueError("Negative Content-Length is not permitted.")
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Invalid Content-Length header."})
            return None

        if length > self.MAX_BODY_SIZE:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "Request body exceeds size limit."}
            )
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

        # 3. GET /api/runs/<run_id>/inspector
        elif path.startswith("/api/runs/") and path.endswith("/inspector"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "runs" and parts[3] == "inspector":
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid run identifier.")
                    return
                inspector = self.mukha_app.get_inspector_view(run_id)
                if inspector is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Run not found.")
                    return
                self._send_json(200, {"ok": True, "inspector": _serialize_dataclass(inspector)})
                return

        # 4. GET /api/runs/<run_id>/artifacts/<artifact_id>
        elif path.startswith("/api/runs/") and "/artifacts/" in path:
            parts = path.strip("/").split("/")
            if len(parts) == 5 and parts[1] == "runs" and parts[3] == "artifacts":
                run_id = parts[2]
                artifact_id = urllib.parse.unquote(parts[4])
                if not _SAFE_ID_PATTERN.match(run_id) or ".." in artifact_id or "/" in artifact_id or "\\" in artifact_id:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid run or artifact identifier.")
                    return
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
                    {"ok": False, "error": _format_public_error(dosh_err)},
                )
            return

        # 4. POST /api/runs
        elif path == "/api/runs":
            raw_paths = body.get("paths", [])
            requirement = body.get("requirement", "read_native")
            profile_str = body.get("profile", "instant")
            recursive = bool(body.get("recursive", True))
            custom_options = body.get("custom_options")
            if not isinstance(custom_options, dict):
                custom_options = None

            if not isinstance(raw_paths, list) or not raw_paths:
                self._send_json(400, {"ok": False, "error": "No input paths provided."})
                return

            try:
                prof = ExecutionProfile.from_string(profile_str)
            except ValueError:
                self._send_json(400, {"ok": False, "error": f"Invalid profile: {profile_str}"})
                return

            # Validate requirement availability before dispatching
            caps_status = MukhaPresenter.audit_capability_status(agni=self.mukha_app.agni)
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
                resp = self.mukha_app.start_run(
                    paths=paths,
                    requirement=requirement,
                    profile=prof,
                    recursive=recursive,
                    custom_options=custom_options,
                )
                if resp.status == StartRunStatus.BUSY:
                    self._send_json(
                        409,
                        {"ok": False, "error": resp.error_message or "An interactive processing run is already active."},
                    )
                elif resp.status == StartRunStatus.INVALID_INPUTS:
                    self._send_json(
                        400,
                        {"ok": False, "error": resp.error_message or "No eligible input documents discovered."},
                    )
                else:
                    self._send_json(200, {"ok": True, "run_id": resp.run_id})
            except DoshError as dosh_err:
                self._send_json(
                    403 if dosh_err.code is FailureCode.SECURITY_DENIED else 400,
                    {"ok": False, "error": _format_public_error(dosh_err)},
                )
            return

        # 5. POST /api/runs/<run_id>/cancel
        elif path.startswith("/api/runs/") and path.endswith("/cancel"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self._send_json(400, {"ok": False, "error": "Invalid run identifier."})
                    return
                cancelled = self.mukha_app.cancel_run(run_id)
                self._send_json(200, {"ok": True, "cancelled": cancelled})
                return

        # 6. POST /api/runs/<run_id>/reveal
        elif path.startswith("/api/runs/") and path.endswith("/reveal"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self._send_json(400, {"ok": False, "error": "Invalid run identifier."})
                    return
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
        self._apply_security_headers(cache_control="no-cache")
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
        safe_ascii_name = target_file.name.replace('"', '').replace('\r', '').replace('\n', '')
        encoded_name = urllib.parse.quote(target_file.name)
        self.send_header(
            "Content-Disposition",
            f'attachment; filename="{safe_ascii_name}"; filename*=UTF-8\'\'{encoded_name}',
        )
        self._apply_security_headers(cache_control="no-store")
        self.end_headers()

        with open(target_file, "rb") as f:
            while chunk := f.read(65536):
                self.wfile.write(chunk)
