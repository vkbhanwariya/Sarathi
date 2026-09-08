"""Mukha Local Web Server HTTP Request Handler for Sarathi V2.

Provides loopback-only (127.0.0.1) HTTP request dispatching, security header enforcement,
host/origin validation, native file picker execution, and confirmed artifact streaming.
"""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.presenter import MukhaPresenter
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
    _is_safe_preview_path,
    _parse_run_request_payload,
    _sanitize_message,
    _serialize_dataclass,
)

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

    def _send_json(self, status: int, data: dict[str, Any], headers: Mapping[str, str] | None = None) -> None:
        """Send a structured JSON response."""
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except Exception:
            body = b'{"ok":false,"error":"Serialization error."}'
            status = 500

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
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
                        self._send_json(404, {"ok": False, "error": "Input file not found."})
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

        # 2e. GET /api/runs/<run_id>/artifacts/<artifact_id>/preview, raw, or pdf_page
        elif path.startswith("/api/runs/") and "/artifacts/" in path and (path.endswith("/preview") or path.endswith("/raw") or path.endswith("/pdf_page")):
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
                        self._send_json(404, {"ok": False, "error": "Artifact not found."})
                    return
                elif action == "pdf_page":
                    art_ref = self.mukha_app.get_confirmed_artifact(run_id, art_id)
                    if art_ref and art_ref.path and art_ref.path.is_file():
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        try:
                            page_num = int(query_params.get("page", ["1"])[0])
                        except ValueError:
                            page_num = 1
                        code, payload = render_pdf_page(str(art_ref.path), page_num)
                        self._send_json(code, payload)
                    else:
                        self._send_json(404, {"ok": False, "error": "Artifact not found."})
                    return

        # 2f. GET /api/preview, /api/preview/raw, /api/preview/pdf_page
        elif path.startswith("/api/preview"):
            query_params = urllib.parse.parse_qs(parsed_url.query)
            path_val = query_params.get("path", [""])[0].strip()
            if not path_val:
                self._send_json(400, {"ok": False, "error": "Missing 'path' query parameter."})
                return
            safe, err_msg = _is_safe_preview_path(path_val)
            if not safe:
                self._send_json(400 if "traversal" in (err_msg or "") else 403, {"ok": False, "error": err_msg})
                return
            if path == "/api/preview/raw":
                target = Path(path_val).resolve()
                if not target.is_file():
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
                    self._send_json(400, {"ok": False, "error": "Invalid run identifier."})
                    return
                inspector = self.mukha_app.get_inspector_view(run_id)
                if inspector is None:
                    self._send_json(404, {"ok": False, "error": "Run not found."})
                    return
                self._send_json(200, {"ok": True, "inspector": _serialize_dataclass(inspector)})
                return

        # 3b. GET /api/runs/<run_id>/diagnostics
        elif path.startswith("/api/runs/") and path.endswith("/diagnostics"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "runs" and parts[3] == "diagnostics":
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self._send_json(400, {"ok": False, "error": "Invalid run identifier."})
                    return
                from sarathi.mukha.web.diagnostics import export_run_diagnostics

                diag = export_run_diagnostics(
                    self.mukha_app.agni,
                    run_id,
                    host=self.headers.get("Host", "127.0.0.1"),
                    port=self.mukha_app.resolved_port,
                )
                query_params = urllib.parse.parse_qs(parsed_url.query)
                headers = {}
                if "download" in query_params:
                    headers["Content-Disposition"] = f'attachment; filename="diagnostics_{run_id}.json"'
                self._send_json(200, diag, headers=headers)
                return

        # 3c. GET /api/runs/<run_id>/summary
        elif path.startswith("/api/runs/") and path.endswith("/summary"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "runs" and parts[3] == "summary":
                run_id = parts[2]
                if not _SAFE_ID_PATTERN.match(run_id):
                    self._send_json(400, {"ok": False, "error": "Invalid run identifier."})
                    return
                summary = self.mukha_app.get_run_summary(run_id)
                if summary is None:
                    self._send_json(404, {"ok": False, "error": "Run summary not found."})
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

        # 3e. GET /api/runs/<run_id>/artifacts/<artifact_id> (download confirmed artifact)
        elif path.startswith("/api/runs/") and "/artifacts/" in path:
            parts = path.strip("/").split("/")
            if len(parts) == 5 and parts[1] == "runs" and parts[3] == "artifacts":
                run_id = parts[2]
                artifact_id = urllib.parse.unquote(parts[4])
                if not _SAFE_ID_PATTERN.match(run_id) or ".." in artifact_id or "/" in artifact_id or "\\" in artifact_id:
                    self._send_json(400, {"ok": False, "error": "Invalid run or artifact identifier."})
                    return
                self._serve_confirmed_artifact(run_id, artifact_id)
                return

        if path.startswith("/api/"):
            self._send_json(404, {"ok": False, "error": "API resource not found."})
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
            from sarathi.mukha.web.review_handler import handle_review_post

            handle_review_post(self, body)
            return
        # 3c. POST /api/plan/preview
        elif path == "/api/plan/preview":
            parsed_intent, err = _parse_run_request_payload(body)
            if err is not None or parsed_intent is None:
                self._send_json(400, {"ok": False, "error": err or "Invalid preview payload."})
                return

            from sarathi.mukha.web.planner import preview_execution_plan

            res = preview_execution_plan(
                agni=self.mukha_app.agni,
                paths=parsed_intent["paths"],
                requirement=parsed_intent["requirement"],
                profile=parsed_intent["profile"],
                recursive=parsed_intent["recursive"],
                custom_options=parsed_intent["custom_options"],
            )
            self._send_json(200 if res.get("ok") else 400, res)
            return

        # 4. POST /api/runs
        elif path == "/api/runs":
            parsed_intent, err = _parse_run_request_payload(body)
            if err is not None or parsed_intent is None:
                self._send_json(400, {"ok": False, "error": err or "Invalid run payload."})
                return

            paths = parsed_intent["paths"]
            requirement = parsed_intent["requirement"]
            prof = parsed_intent["profile"]
            recursive = parsed_intent["recursive"]
            custom_options = parsed_intent["custom_options"]

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

        if path.startswith("/api/"):
            self._send_json(404, {"ok": False, "error": "API endpoint not found."})
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found.")

    def _serve_static_resource(self, filename: str, content_type: str) -> None:
        """Serve packaged static asset using importlib.resources."""
        from sarathi.mukha.web.static_handler import serve_static_resource

        serve_static_resource(self, filename, content_type)

    def _serve_asset_resource(self, filename: str, content_type: str) -> None:
        """Serve packaged asset resource from sarathi.mukha.web.assets or disk."""
        from sarathi.mukha.web.static_handler import serve_asset_resource

        serve_asset_resource(self, filename, content_type)

    def _serve_sse_stream(self) -> None:
        """Stream real-time presentation state and progress events over Server-Sent Events (SSE)."""
        from sarathi.mukha.web.static_handler import serve_sse_stream

        serve_sse_stream(self)

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
