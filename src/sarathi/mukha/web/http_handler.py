"""Mukha Local Web Server HTTP Request Handler for Sarathi V2.

Provides loopback-only (127.0.0.1) HTTP request dispatching, security header enforcement,
host/origin validation, native file picker execution, and confirmed artifact streaming.
"""

from __future__ import annotations

import importlib.resources
import json
import mimetypes
import re
import socket
import time
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import ReviewIntent
from sarathi.mukha.web.native_picker import NativePicker
from sarathi.mukha.web.preview import (
    build_artifact_preview,
    build_document_preview,
    build_input_preview,
    render_pdf_page,
    stream_confirmed_artifact,
    stream_raw_document,
)
from sarathi.mukha.web.security import (
    _ALLOWED_LOOPBACK_HOSTNAMES,
    _format_public_error,
    _is_authorized_loopback_host,
    _is_authorized_loopback_origin,
    _sanitize_message,
    _serialize_dataclass,
)
from sarathi.sankalpa import ExecutionProfile

if TYPE_CHECKING:
    from sarathi.mukha.web.server import MukhaWebServer


_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


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


__all__ = [
    "MukhaHTTPHandler",
    "StartRunResponse",
    "StartRunStatus",
    "_ALLOWED_LOOPBACK_HOSTNAMES",
    "_format_public_error",
    "_is_authorized_loopback_host",
    "_is_authorized_loopback_origin",
    "_sanitize_message",
    "_serialize_dataclass",
]


class MukhaHTTPHandler(BaseHTTPRequestHandler):
    """Loopback-only HTTP request handler for the interactive Mukha presentation server."""

    MAX_BODY_SIZE: int = 1_048_576  # 1 MB strict limit
    _SECURITY_CSP: str = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'self' blob:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
        self.send_header("X-Frame-Options", "DENY")
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
        elif path.startswith("/js/"):
            js_rel = path.removeprefix("/js/")
            if ".." in js_rel or "\\" in js_rel:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid script path.")
                return
            filename = f"js/{js_rel}"
            self._serve_static_resource(filename, "application/javascript; charset=utf-8")
            return
        elif path.startswith("/assets/"):
            asset_filename = path.removeprefix("/assets/")
            if ".." in asset_filename or "/" in asset_filename or "\\" in asset_filename:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid asset identifier.")
                return
            mime = mimetypes.guess_type(asset_filename)[0] or "application/octet-stream"
            self._serve_asset_resource(asset_filename, mime)
            return

        # 2. GET /api/state
        elif path == "/api/state":
            app_state = self.mukha_app.get_application_view_state()
            self._send_json(
                200,
                {
                    "ok": True,
                    "schema_version": app_state.schema_version,
                    "state_revision": app_state.state_revision,
                    "state": _serialize_dataclass(app_state),
                },
            )
            return

        # 2a. GET /api/events (Server-Sent Events)
        elif path == "/api/events":
            self._serve_sse_stream()
            return

        # 2b. GET /api/history
        elif path == "/api/history":
            limit = 50
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if "limit" in query_params:
                try:
                    limit = max(1, min(int(query_params["limit"][0]), 200))
                except ValueError:
                    self._send_json(400, {"ok": False, "error": "Invalid limit parameter."})
                    return
            history = self.mukha_app.get_run_history(limit=limit)
            self._send_json(200, {"ok": True, "history": [_serialize_dataclass(h) for h in history]})
            return

        # 2c. GET /api/review or /api/runs/<run_id>/review
        elif path == "/api/review" or (path.startswith("/api/runs/") and path.endswith("/review")):
            run_id = None
            if path.startswith("/api/runs/"):
                parts = path.strip("/").split("/")
                if len(parts) == 4:
                    run_id = parts[2]
            items = self.mukha_app.get_review_items(run_id)
            self._send_json(200, {"ok": True, "items": list(items)})
            return

        # 2d. GET /api/inputs/<input_id>/preview or raw or pdf_page
        elif path.startswith("/api/inputs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "inputs":
                input_id = urllib.parse.unquote(parts[2])
                action = parts[3]
                if action == "preview":
                    self._serve_input_preview(input_id)
                    return
                elif action == "raw":
                    target = None
                    if hasattr(self.mukha_app, "get_input_path"):
                        target = self.mukha_app.get_input_path(input_id)
                    if target is None and hasattr(self.mukha_app, "runner"):
                        target = self.mukha_app.runner.get_input_path(input_id)
                    if target and target.is_file():
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        stream_raw_document(self, target, download="download" in query_params)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND, "Input file not found.")
                    return
                elif action == "pdf_page":
                    target = None
                    if hasattr(self.mukha_app, "get_input_path"):
                        target = self.mukha_app.get_input_path(input_id)
                    if target is None and hasattr(self.mukha_app, "runner"):
                        target = self.mukha_app.runner.get_input_path(input_id)
                    if target and target.is_file():
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        try:
                            page_num = int(query_params.get("page", ["1"])[0])
                        except ValueError:
                            page_num = 1
                        code, payload = render_pdf_page(str(target), page_num)
                        self._send_json(code, payload)
                    else:
                        self._send_json(404, {"ok": False, "error": "Input file not found."})
                    return

        # 2e. GET /api/runs/<run_id>/artifacts/<artifact_id>/preview or raw
        elif path.startswith("/api/runs/") and "/artifacts/" in path and (path.endswith("/preview") or path.endswith("/raw")):
            parts = path.strip("/").split("/")
            if len(parts) == 6 and parts[1] == "runs" and parts[3] == "artifacts":
                run_id = parts[2]
                art_id = urllib.parse.unquote(parts[4])
                action = parts[5]
                if action == "preview":
                    self._serve_artifact_preview(run_id, art_id)
                    return
                elif action == "raw":
                    art_ref = self.mukha_app.get_confirmed_artifact(run_id, art_id)
                    if art_ref and art_ref.path and art_ref.path.is_file():
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        stream_raw_document(self, art_ref.path, download="download" in query_params)
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND, "Artifact not found.")
                    return

        # 2f. GET /api/preview, /api/preview/raw, /api/preview/pdf_page
        elif path.startswith("/api/preview"):
            query_params = urllib.parse.parse_qs(parsed_url.query)
            path_val = query_params.get("path", [""])[0].strip()
            if not path_val:
                self._send_json(400, {"ok": False, "error": "Missing 'path' query parameter."})
                return
            if path == "/api/preview/raw":
                target = Path(path_val).resolve()
                if not target.is_file() or (".." in path_val and ("../" in path_val or "..\\" in path_val)):
                    self.send_error(HTTPStatus.NOT_FOUND, "Document file not found.")
                    return
                stream_raw_document(self, target, download="download" in query_params)
                return
            elif path == "/api/preview/pdf_page":
                try:
                    page_num = int(query_params.get("page", ["1"])[0])
                except ValueError:
                    page_num = 1
                code, payload = render_pdf_page(path_val, page_num)
                self._send_json(code, payload)
                return
            elif path == "/api/preview":
                self._serve_document_preview(path_val)
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

        # 3b. GET /api/runs/<run_id>/diagnostics
        elif path.startswith("/api/runs/") and path.endswith("/diagnostics"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "runs" and parts[3] == "diagnostics":
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid run identifier.")
                    return
                from sarathi.mukha.web.diagnostics import export_run_diagnostics

                diag = export_run_diagnostics(
                    self.mukha_app.agni,
                    run_id,
                    host=self.headers.get("Host", "127.0.0.1"),
                    port=self.mukha_app.resolved_port,
                )
                self._send_json(200, diag)
                return

        # 3c. GET /api/runs/<run_id>/summary
        elif path.startswith("/api/runs/") and path.endswith("/summary"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "runs" and parts[3] == "summary":
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self.send_error(HTTPStatus.BAD_REQUEST, "Invalid run identifier.")
                    return
                summary = self.mukha_app.get_run_summary(run_id)
                if summary is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Run summary not found.")
                    return
                self._send_json(200, {"ok": True, "summary": _serialize_dataclass(summary)})
                return

        # 3d. GET /api/runs/compare?run_a=...&run_b=...
        elif path == "/api/runs/compare":
            query_params = urllib.parse.parse_qs(parsed_url.query)
            run_a = query_params.get("run_a", [""])[0].strip()
            run_b = query_params.get("run_b", [""])[0].strip()
            if not run_a or not run_b:
                self._send_json(400, {"ok": False, "error": "Both run_a and run_b query parameters are required."})
                return
            if not _SAFE_ID_PATTERN.match(run_a) or not _SAFE_ID_PATTERN.match(run_b):
                self._send_json(400, {"ok": False, "error": "Invalid run identifier format."})
                return
            from sarathi.mukha.web.comparison import compare_runs

            cmp_res = compare_runs(self.mukha_app.agni, run_a, run_b)
            self._send_json(200, cmp_res)
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
            raw_paths = body.get("paths")
            if raw_paths is None or not isinstance(raw_paths, list):
                self._send_json(400, {"ok": False, "error": "'paths' must be a list."})
                return
            if not isinstance(body.get("recursive", True), bool):
                self._send_json(400, {"ok": False, "error": "'recursive' must be a boolean."})
                return
            recursive = bool(body.get("recursive", True))

            paths = [Path(p) for p in raw_paths if isinstance(p, str) and p.strip()]
            try:
                inputs, input_selection, preflight = MukhaPresenter.intake_from_paths(
                    paths,
                    kavacha=self.mukha_app.kavacha,
                    runtime_root=self.mukha_app.runtime_root,
                    output_root=self.mukha_app.output_root,
                    recursive=recursive,
                )
                if hasattr(self.mukha_app, "runner") and self.mukha_app.runner is not None:
                    self.mukha_app.runner.set_intake_selection(input_selection, inputs)
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

        # 3b. POST /api/review
        elif path == "/api/review":
            item_id = body.get("item_id")
            action = body.get("action_id") or body.get("action")
            if not isinstance(item_id, str) or not item_id.strip():
                self._send_json(400, {"ok": False, "error": "item_id must be a non-empty string."})
                return
            if not isinstance(action, str) or not action.strip():
                self._send_json(400, {"ok": False, "error": "action or action_id must be a non-empty string."})
                return
            act = action.strip()
            act_mapped = "validate_edit" if act == "edit" else ("unresolved" if act == "dismiss" else act)
            if act_mapped not in ("accept", "validate_edit", "retry", "unresolved"):
                self._send_json(400, {"ok": False, "error": f"Invalid review action: '{action}'."})
                return
            intent = ReviewIntent(
                item_id=item_id.strip(),
                attempt_id=str(body.get("attempt_id") or "att-1"),
                action_id=act_mapped,
                proposed_value=str(body["proposed_value"]) if body.get("proposed_value") is not None else None,
                expected_revision=int(body["expected_revision"]) if body.get("expected_revision") is not None else None,
            )
            applied = self.mukha_app.apply_review_intent(intent)
            self._send_json(200, {"ok": True, "action": act_mapped, "item_id": intent.item_id, "applied": applied})
        # 3c. POST /api/plan/preview
        elif path == "/api/plan/preview":
            raw_paths = body.get("paths")
            requirement = body.get("requirement", "read_native")
            profile_str = body.get("profile", "instant")
            recursive = bool(body.get("recursive", True))
            custom_options = body.get("custom_options")

            if not isinstance(raw_paths, list) or not raw_paths:
                self._send_json(400, {"ok": False, "error": "No input paths provided."})
                return

            try:
                prof = ExecutionProfile.from_string(profile_str) if isinstance(profile_str, str) else ExecutionProfile.INSTANT
            except ValueError:
                prof = ExecutionProfile.INSTANT

            paths = [Path(p) for p in raw_paths if isinstance(p, str) and p.strip()]
            from sarathi.mukha.web.planner import preview_execution_plan

            res = preview_execution_plan(
                agni=self.mukha_app.agni,
                paths=paths,
                requirement=requirement,
                profile=prof,
                recursive=recursive,
                custom_options=custom_options,
            )
            self._send_json(200 if res.get("ok") else 400, res)
            return

        # 4. POST /api/runs
        elif path == "/api/runs":
            raw_paths = body.get("paths")
            requirement = body.get("requirement", "read_native")
            profile_str = body.get("profile", "instant")
            if not isinstance(body.get("recursive", True), bool):
                self._send_json(400, {"ok": False, "error": "'recursive' must be a boolean."})
                return
            recursive = bool(body.get("recursive", True))

            if "custom_options" in body and body["custom_options"] is not None and not isinstance(body["custom_options"], dict):
                self._send_json(400, {"ok": False, "error": "'custom_options' must be an object or null."})
                return
            custom_options = body.get("custom_options")

            if not isinstance(raw_paths, list) or not raw_paths or not all(isinstance(p, str) and p.strip() for p in raw_paths):
                self._send_json(400, {"ok": False, "error": "No input paths provided."})
                return

            if not isinstance(requirement, str) or not requirement.strip():
                self._send_json(400, {"ok": False, "error": "requirement must be a non-empty string."})
                return

            if not isinstance(profile_str, str) or not profile_str.strip():
                self._send_json(400, {"ok": False, "error": "profile must be a non-empty string."})
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

        # 7. POST /api/history/clear
        elif path == "/api/history/clear":
            cleared = self.mukha_app.clear_history()
            self._send_json(200, {"ok": True, "cleared": cleared})
            return

        # 8. POST /api/cache/clear
        elif path == "/api/cache/clear":
            count = self.mukha_app.clear_cache()
            self._send_json(200, {"ok": True, "cleared_entries": count})
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

    def _serve_asset_resource(self, filename: str, content_type: str) -> None:
        """Serve packaged asset resource from sarathi.mukha.web.assets or disk."""
        try:
            pkg = importlib.resources.files("sarathi.mukha.web.assets")
            resource = pkg.joinpath(filename)
            content = resource.read_bytes()
        except Exception:
            local_path = Path(__file__).parent / "assets" / filename
            if not local_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"Asset {filename} not found.")
                return
            content = local_path.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self._apply_security_headers(cache_control="public, max-age=3600")
        self.end_headers()
        self.wfile.write(content)

    def _serve_sse_stream(self) -> None:
        """Stream real-time presentation state and progress events over Server-Sent Events (SSE)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._apply_security_headers(cache_control="no-cache")
        self.end_headers()

        last_revision: int = -1
        last_serialized: str | None = None
        last_ping = time.time()

        try:
            while not getattr(self.server, "_shutting_down", False):
                now = time.time()
                runner_rev = getattr(getattr(self.mukha_app, "runner", None), "state_revision", None)
                app_state = self.mukha_app.get_application_view_state()
                is_running = bool(app_state.active_run and app_state.active_run.status == "RUNNING")

                if runner_rev is None or runner_rev != last_revision or is_running:
                    serialized = json.dumps(
                        {
                            "ok": True,
                            "schema_version": app_state.schema_version,
                            "state_revision": app_state.state_revision,
                            "state": _serialize_dataclass(app_state),
                        },
                        ensure_ascii=False,
                    )
                    if serialized != last_serialized or runner_rev != last_revision:
                        last_serialized = serialized
                        last_revision = app_state.state_revision if runner_rev is not None else -1
                        payload = f"event: state\ndata: {serialized}\n\n".encode("utf-8")
                        self.wfile.write(payload)
                        self.wfile.flush()

                if now - last_ping >= 15.0:
                    last_ping = now
                    self.wfile.write(b"event: ping\ndata: {}\n\n")
                    self.wfile.flush()

                time.sleep(0.5 if is_running else 1.5)
        except (ConnectionResetError, BrokenPipeError, socket.error, OSError):
            return
        except Exception:
            return

    def _serve_document_preview(self, path_str: str) -> None:
        """Serve safe structured preview data for a candidate input document or output file."""
        status_code, payload = build_document_preview(path_str)
        self._send_json(status_code, payload)

    def _serve_input_preview(self, input_id: str) -> None:
        """Serve structured preview for an authorized intake input ID."""
        status_code, payload = build_input_preview(self.mukha_app, input_id)
        self._send_json(status_code, payload)

    def _serve_artifact_preview(self, run_id: str, artifact_id: str) -> None:
        """Serve structured preview for a confirmed run artifact."""
        status_code, payload = build_artifact_preview(self.mukha_app, run_id, artifact_id)
        self._send_json(status_code, payload)

    def _serve_confirmed_artifact(self, run_id: str, artifact_id: str) -> None:
        """Stream confirmed artifact file safely by resolving run_id and artifact_id."""
        stream_confirmed_artifact(self, self.mukha_app, run_id, artifact_id)
