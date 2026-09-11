"""Starlette transport for the local Mukha web application."""

from __future__ import annotations

import asyncio
import importlib.resources
import json
import mimetypes
import re
import time
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from starlette.applications import Starlette
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import ReviewIntent
from sarathi.mukha.web.native_picker import NativePicker
from sarathi.mukha.web.preview import (
    build_artifact_preview,
    build_document_preview,
    build_input_preview,
    render_pdf_page,
)
from sarathi.mukha.web.runner import StartRunStatus
from sarathi.mukha.web.security import (
    _format_public_error,
    _is_authorized_loopback_host,
    _is_authorized_loopback_origin,
    _is_safe_preview_path,
    _parse_run_request_payload,
    _serialize_dataclass,
)

if TYPE_CHECKING:
    from sarathi.mukha.web.server import MukhaWebServer


_MAX_BODY_SIZE = 1_048_576
_SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_SECURITY_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'self' blob:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


def _json(status: int, data: dict[str, Any], headers: dict[str, str] | None = None) -> JSONResponse:
    """Return a UTF-8 JSON response using the canonical API envelope."""
    return JSONResponse(data, status_code=status, headers=headers)


def _static_bytes(filename: str) -> bytes | None:
    """Read one packaged Mukha static resource without exposing arbitrary paths."""
    try:
        resource = importlib.resources.files("sarathi.mukha.web")
        for part in filename.split("/"):
            resource = resource.joinpath(part)
        return resource.read_bytes()
    except Exception:
        path = Path(__file__).parent.joinpath(*filename.split("/"))
        if path.is_file():
            return path.read_bytes()
        return None


def _static_response(filename: str, content_type: str, cache_control: str = "no-cache") -> Response:
    content = _static_bytes(filename)
    if content is None:
        return Response("Resource not found.", status_code=404)
    return Response(content, media_type=content_type, headers={"Cache-Control": cache_control})


def _content_disposition(path: Path, *, download: bool) -> str:
    disposition = "attachment" if download else "inline"
    safe_name = path.name.replace('"', "").replace("\r", "").replace("\n", "")
    encoded_name = urllib.parse.quote(path.name)
    return f'{disposition}; filename="{safe_name}"; filename*=UTF-8\'\'{encoded_name}'


def _raw_file_response(target: Path, *, download: bool = False, media_type: str | None = None) -> Response:
    if not target.is_file():
        return Response("Document file not found.", status_code=404)
    resolved_type = media_type or mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    headers = {
        "Content-Disposition": _content_disposition(target, download=download),
        "X-Frame-Options": "SAMEORIGIN",
        "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'",
        "Cache-Control": "no-store",
    }
    return FileResponse(target, media_type=resolved_type, headers=headers)


def _validated_run_id(run_id: str) -> bool:
    return bool(_SAFE_ID_PATTERN.fullmatch(run_id))


def _confirmed_artifact_response(
    mukha: MukhaWebServer,
    run_id: str,
    artifact_id: str,
    *,
    inline: bool,
) -> Response:
    if not _validated_run_id(run_id) or ".." in artifact_id or "/" in artifact_id or "\\" in artifact_id:
        return _json(400, {"ok": False, "error": "Invalid run or artifact identifier."})

    art_ref = mukha.get_confirmed_artifact(run_id, artifact_id)
    if art_ref is None or not art_ref.path or not art_ref.path.is_file():
        return Response("Confirmed artifact not found.", status_code=404)

    target = art_ref.path.resolve()
    allowed = False
    for root in (mukha.output_root.resolve(), mukha.runtime_root.resolve()):
        try:
            target.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        return Response("Access to file outside authorized roots is denied.", status_code=403)

    return _raw_file_response(
        target,
        download=not inline,
        media_type=art_ref.media_type or None,
    )


class LoopbackSecurityMiddleware:
    """Enforce loopback Host/Origin rules and canonical response security headers."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @staticmethod
    def _secure_headers(headers: MutableHeaders) -> None:
        if "content-security-policy" not in headers:
            headers["Content-Security-Policy"] = _SECURITY_CSP
        if "referrer-policy" not in headers:
            headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if "x-content-type-options" not in headers:
            headers["X-Content-Type-Options"] = "nosniff"
        if "x-frame-options" not in headers:
            headers["X-Frame-Options"] = "DENY"
        if "cache-control" not in headers:
            headers["Cache-Control"] = "no-store"

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers", [])
        header_map = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in raw_headers}
        host = header_map.get("host", "")
        origin = header_map.get("origin")

        if not _is_authorized_loopback_host(host):
            response = _json(403, {"ok": False, "error": "Forbidden Host header."})
            self._secure_headers(response.headers)
            await response(scope, receive, send)
            return
        if origin is not None and not _is_authorized_loopback_origin(origin):
            response = _json(403, {"ok": False, "error": "Forbidden Origin header."})
            self._secure_headers(response.headers)
            await response(scope, receive, send)
            return

        async def secure_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                self._secure_headers(MutableHeaders(scope=message))
            await send(message)

        await self.app(scope, receive, secure_send)


async def _read_json_object(request: Request) -> tuple[dict[str, Any] | None, Response | None]:
    """Read one bounded JSON object request body."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
            if length < 0:
                raise ValueError
        except ValueError:
            return None, _json(400, {"ok": False, "error": "Invalid Content-Length header."})
        if length > _MAX_BODY_SIZE:
            return None, _json(413, {"ok": False, "error": "Request body exceeds size limit."})

    raw = await request.body()
    if len(raw) > _MAX_BODY_SIZE:
        return None, _json(413, {"ok": False, "error": "Request body exceeds size limit."})
    if not raw:
        return {}, None
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, _json(400, {"ok": False, "error": "Malformed JSON payload."})
    if not isinstance(parsed, dict):
        return None, _json(400, {"ok": False, "error": "JSON body must be an object."})
    return parsed, None


def _parse_review_intent(body: dict[str, Any]) -> tuple[ReviewIntent | None, str | None, int]:
    """Translate an HTTP review payload into a validated review intent."""
    item_id = body.get("item_id")
    action = body.get("action_id") or body.get("action")
    attempt_id = body.get("attempt_id")
    run_id = body.get("run_id")

    if not isinstance(item_id, str) or not item_id.strip():
        return None, "item_id must be a non-empty string.", 400
    if not isinstance(action, str) or not action.strip():
        return None, "action or action_id must be a non-empty string.", 400
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        return None, "attempt_id must be a non-empty string.", 400
    if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
        return None, "run_id must be a non-empty string when provided.", 400

    action_id = action.strip()
    if action_id == "edit":
        action_id = "validate_edit"
    elif action_id in ("dismiss", "unresolved"):
        action_id = "unresolved"

    if action_id not in ("accept", "validate_edit", "retry", "unresolved"):
        return None, f"Invalid review action: '{action}'.", 400
    if action_id in ("validate_edit", "retry"):
        return None, f"Review action '{action_id}' is currently unsupported by runtime capability.", 400

    expected_revision = None
    if body.get("expected_revision") is not None:
        try:
            expected_revision = int(body["expected_revision"])
        except (TypeError, ValueError):
            return None, "expected_revision must be an integer.", 400

    return (
        ReviewIntent(
            item_id=item_id.strip(),
            attempt_id=attempt_id.strip(),
            action_id=action_id,
            run_id=run_id.strip() if run_id else None,
            proposed_value=str(body["proposed_value"]) if body.get("proposed_value") is not None else None,
            expected_revision=expected_revision,
        ),
        None,
        200,
    )


def create_mukha_app(mukha: MukhaWebServer) -> Starlette:
    """Build the Starlette application around an existing Mukha presentation façade."""

    async def root(_: Request) -> Response:
        return _static_response("ui/index.html", "text/html")

    async def ui_asset(request: Request) -> Response:
        name = request.path_params["path"]
        if name not in {"app.js", "app.css"}:
            return Response("UI asset not found.", status_code=404)
        mime = "application/javascript" if name.endswith(".js") else "text/css"
        return _static_response(f"ui/{name}", mime, "public, max-age=3600")

    async def packaged_asset(request: Request) -> Response:
        name = request.path_params["path"]
        if ".." in name or "/" in name or "\\" in name:
            return Response("Invalid asset identifier.", status_code=400)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return _static_response(f"assets/{name}", mime, "public, max-age=3600")

    async def api_state(_: Request) -> Response:
        state = mukha.get_application_view_state()
        return _json(
            200,
            {
                "ok": True,
                "schema_version": state.schema_version,
                "state_revision": state.state_revision,
                "state": _serialize_dataclass(state),
            },
        )

    async def api_events(request: Request) -> Response:
        async def events() -> AsyncIterator[bytes]:
            last_revision = -1
            last_serialized: str | None = None
            last_ping = time.monotonic()
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    state = mukha.get_application_view_state()
                    runner_revision = mukha.runner.state_revision
                    is_running = bool(state.active_run and state.active_run.status == "RUNNING")
                    if runner_revision != last_revision or is_running:
                        serialized = json.dumps(
                            {
                                "ok": True,
                                "schema_version": state.schema_version,
                                "state_revision": state.state_revision,
                                "state": _serialize_dataclass(state),
                            },
                            ensure_ascii=False,
                        )
                        if serialized != last_serialized or runner_revision != last_revision:
                            last_serialized = serialized
                            last_revision = state.state_revision
                            yield f"event: state\ndata: {serialized}\n\n".encode("utf-8")

                    now = time.monotonic()
                    if now - last_ping >= 15.0:
                        last_ping = now
                        yield b"event: ping\ndata: {}\n\n"
                    await asyncio.sleep(0.5 if is_running else 1.5)
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    async def api_history(request: Request) -> Response:
        raw = request.query_params.get("limit", "50")
        try:
            limit = max(1, min(int(raw), 200))
        except ValueError:
            return _json(400, {"ok": False, "error": "Invalid limit parameter."})
        history = mukha.get_run_history(limit=limit)
        return _json(200, {"ok": True, "history": [_serialize_dataclass(item) for item in history]})

    async def api_review_get(request: Request) -> Response:
        run_id = request.path_params.get("run_id")
        return _json(200, {"ok": True, "items": list(mukha.get_review_items(run_id))})

    async def input_preview(request: Request) -> Response:
        status, payload = build_input_preview(mukha, request.path_params["input_id"])
        return _json(status, payload)

    async def input_raw(request: Request) -> Response:
        target = mukha.get_input_path(request.path_params["input_id"])
        if target is None:
            return _json(404, {"ok": False, "error": "Input file not found."})
        return _raw_file_response(target, download="download" in request.query_params)

    async def input_pdf_page(request: Request) -> Response:
        target = mukha.get_input_path(request.path_params["input_id"])
        if target is None or not target.is_file():
            return _json(404, {"ok": False, "error": "Input file not found."})
        try:
            page = int(request.query_params.get("page", "1"))
        except ValueError:
            page = 1
        status, payload = render_pdf_page(str(target), page)
        return _json(status, payload)

    async def artifact_preview(request: Request) -> Response:
        status, payload = build_artifact_preview(
            mukha,
            request.path_params["run_id"],
            request.path_params["artifact_id"],
        )
        return _json(status, payload)

    async def artifact_raw(request: Request) -> Response:
        return _confirmed_artifact_response(
            mukha,
            request.path_params["run_id"],
            request.path_params["artifact_id"],
            inline=True,
        )

    async def artifact_pdf_page(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        artifact_id = request.path_params["artifact_id"]
        art_ref = mukha.get_confirmed_artifact(run_id, artifact_id)
        if art_ref is None or not art_ref.path or not art_ref.path.is_file():
            return _json(404, {"ok": False, "error": "Artifact not found."})
        try:
            page = int(request.query_params.get("page", "1"))
        except ValueError:
            page = 1
        status, payload = render_pdf_page(str(art_ref.path), page)
        return _json(status, payload)

    async def generic_preview(request: Request) -> Response:
        path_value = request.query_params.get("path", "").strip()
        if not path_value:
            return _json(400, {"ok": False, "error": "Missing 'path' query parameter."})
        safe, error = _is_safe_preview_path(path_value)
        if not safe:
            return _json(400 if "traversal" in (error or "") else 403, {"ok": False, "error": error})
        status, payload = build_document_preview(path_value)
        return _json(status, payload)

    async def generic_preview_raw(request: Request) -> Response:
        path_value = request.query_params.get("path", "").strip()
        if not path_value:
            return _json(400, {"ok": False, "error": "Missing 'path' query parameter."})
        safe, error = _is_safe_preview_path(path_value)
        if not safe:
            return _json(400 if "traversal" in (error or "") else 403, {"ok": False, "error": error})
        return _raw_file_response(Path(path_value).resolve(), download="download" in request.query_params)

    async def generic_preview_pdf_page(request: Request) -> Response:
        path_value = request.query_params.get("path", "").strip()
        if not path_value:
            return _json(400, {"ok": False, "error": "Missing 'path' query parameter."})
        safe, error = _is_safe_preview_path(path_value)
        if not safe:
            return _json(400 if "traversal" in (error or "") else 403, {"ok": False, "error": error})
        try:
            page = int(request.query_params.get("page", "1"))
        except ValueError:
            page = 1
        status, payload = render_pdf_page(path_value, page)
        return _json(status, payload)

    async def run_inspector(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        if not _validated_run_id(run_id):
            return _json(400, {"ok": False, "error": "Invalid run identifier."})
        inspector = mukha.get_inspector_view(run_id)
        if inspector is None:
            return _json(404, {"ok": False, "error": "Run not found."})
        return _json(200, {"ok": True, "inspector": _serialize_dataclass(inspector)})

    async def run_diagnostics(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        if not _validated_run_id(run_id):
            return _json(400, {"ok": False, "error": "Invalid run identifier."})
        from sarathi.mukha.web.diagnostics import export_run_diagnostics

        payload = export_run_diagnostics(
            mukha.agni,
            run_id,
            host=request.headers.get("host", "127.0.0.1"),
            port=mukha.resolved_port,
        )
        headers = None
        if "download" in request.query_params:
            headers = {"Content-Disposition": f'attachment; filename="diagnostics_{run_id}.json"'}
        return _json(200, payload, headers=headers)

    async def run_summary(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        if not _validated_run_id(run_id):
            return _json(400, {"ok": False, "error": "Invalid run identifier."})
        summary = mukha.get_run_summary(run_id)
        if summary is None:
            return _json(404, {"ok": False, "error": "Run summary not found."})
        return _json(200, {"ok": True, "summary": _serialize_dataclass(summary)})

    async def compare_runs_route(request: Request) -> Response:
        run_a = request.query_params.get("run_a", "").strip()
        run_b = request.query_params.get("run_b", "").strip()
        if not run_a or not run_b:
            return _json(400, {"ok": False, "error": "Both run_a and run_b query parameters are required."})
        if not _validated_run_id(run_a) or not _validated_run_id(run_b):
            return _json(400, {"ok": False, "error": "Invalid run identifier format."})
        from sarathi.mukha.web.comparison import compare_runs

        return _json(200, compare_runs(mukha.agni, run_a, run_b))

    async def invalid_artifact_path(_: Request) -> Response:
        return _json(400, {"ok": False, "error": "Invalid run or artifact identifier."})

    async def artifact_download(request: Request) -> Response:
        return _confirmed_artifact_response(
            mukha,
            request.path_params["run_id"],
            request.path_params["artifact_id"],
            inline=False,
        )

    async def browse_files(_: Request) -> Response:
        result = NativePicker.browse_files()
        if not result.is_available:
            return _json(200, {"ok": False, "error": result.error_message})
        return _json(200, {"ok": True, "paths": list(result.paths)})

    async def browse_folder(_: Request) -> Response:
        result = NativePicker.browse_folder()
        if not result.is_available:
            return _json(200, {"ok": False, "error": result.error_message})
        return _json(200, {"ok": True, "paths": list(result.paths)})

    async def intake(request: Request) -> Response:
        body, error_response = await _read_json_object(request)
        if error_response is not None:
            return error_response
        assert body is not None
        raw_paths = body.get("paths")
        if not isinstance(raw_paths, list):
            return _json(400, {"ok": False, "error": "'paths' must be a list."})
        if not isinstance(body.get("recursive", True), bool):
            return _json(400, {"ok": False, "error": "'recursive' must be a boolean."})
        paths = [Path(path) for path in raw_paths if isinstance(path, str) and path.strip()]
        try:
            inputs, selection, preflight = MukhaPresenter.intake_from_paths(
                paths,
                kavacha=mukha.kavacha,
                runtime_root=mukha.runtime_root,
                output_root=mukha.output_root,
                recursive=body.get("recursive", True),
            )
            mukha.runner.set_intake_selection(selection, inputs)
            return _json(
                200,
                {
                    "ok": True,
                    "input_selection": _serialize_dataclass(selection),
                    "preflight": _serialize_dataclass(preflight),
                },
            )
        except DoshError as error:
            return _json(
                403 if error.code is FailureCode.SECURITY_DENIED else 400,
                {"ok": False, "error": _format_public_error(error)},
            )

    async def review_post(request: Request) -> Response:
        body, error_response = await _read_json_object(request)
        if error_response is not None:
            return error_response
        assert body is not None
        intent, error, status = _parse_review_intent(body)
        if intent is None or error is not None:
            return _json(status, {"ok": False, "error": error or "Invalid review payload."})
        if not mukha.apply_review_intent(intent):
            return _json(
                400,
                {
                    "ok": False,
                    "error": "Review intent rejected: foreign run, stale attempt, duplicate submission, or invalid item.",
                },
            )
        return _json(200, {"ok": True, "action": intent.action_id, "item_id": intent.item_id, "applied": True})

    async def plan_preview(request: Request) -> Response:
        body, error_response = await _read_json_object(request)
        if error_response is not None:
            return error_response
        assert body is not None
        parsed, error = _parse_run_request_payload(body)
        if parsed is None or error is not None:
            return _json(400, {"ok": False, "error": error or "Invalid preview payload."})
        from sarathi.mukha.web.planner import preview_execution_plan

        result = preview_execution_plan(
            agni=mukha.agni,
            paths=parsed["paths"],
            requirement=parsed["requirement"],
            profile=parsed["profile"],
            recursive=parsed["recursive"],
            custom_options=parsed["custom_options"],
        )
        return _json(200 if result.get("ok") else 400, result)

    async def start_run(request: Request) -> Response:
        body, error_response = await _read_json_object(request)
        if error_response is not None:
            return error_response
        assert body is not None
        parsed, error = _parse_run_request_payload(body)
        if parsed is None or error is not None:
            return _json(400, {"ok": False, "error": error or "Invalid run payload."})

        requirement = parsed["requirement"]
        statuses = MukhaPresenter.audit_capability_status(agni=mukha.agni)
        available, reason = statuses.get(requirement, (False, "Capability unavailable."))
        if not available or requirement not in set(mukha.registered_capabilities):
            return _json(
                400,
                {"ok": False, "error": f"Selected requirement '{requirement}' is unavailable: {reason}"},
            )
        try:
            result = mukha.start_run(
                paths=parsed["paths"],
                requirement=requirement,
                profile=parsed["profile"],
                recursive=parsed["recursive"],
                custom_options=parsed["custom_options"],
            )
        except DoshError as run_error:
            return _json(
                403 if run_error.code is FailureCode.SECURITY_DENIED else 400,
                {"ok": False, "error": _format_public_error(run_error)},
            )
        if result.status == StartRunStatus.BUSY:
            return _json(
                409,
                {"ok": False, "error": result.error_message or "An interactive processing run is already active."},
            )
        if result.status == StartRunStatus.INVALID_INPUTS:
            return _json(
                400,
                {"ok": False, "error": result.error_message or "No eligible input documents discovered."},
            )
        return _json(200, {"ok": True, "run_id": result.run_id})

    async def cancel_run(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        if not _validated_run_id(run_id):
            return _json(400, {"ok": False, "error": "Invalid run identifier."})
        return _json(200, {"ok": True, "cancelled": mukha.cancel_run(run_id)})

    async def reveal_run(request: Request) -> Response:
        run_id = request.path_params["run_id"]
        if not _validated_run_id(run_id):
            return _json(400, {"ok": False, "error": "Invalid run identifier."})
        return _json(200, {"ok": True, "revealed": mukha.reveal_output_directory(run_id)})

    async def clear_history(_: Request) -> Response:
        return _json(200, {"ok": True, "cleared": mukha.clear_history()})

    async def clear_cache(_: Request) -> Response:
        return _json(200, {"ok": True, "cleared_entries": mukha.clear_cache()})

    async def api_not_found(_: Request) -> Response:
        return _json(404, {"ok": False, "error": "API resource not found."})

    routes = [
        Route("/", root),
        Route("/index.html", root),
        Route("/ui/{path:path}", ui_asset),
        Route("/assets/{path:path}", packaged_asset),
        Route("/api/state", api_state),
        Route("/api/events", api_events),
        Route("/api/history", api_history),
        Route("/api/review", api_review_get, methods=["GET"]),
        Route("/api/runs/{run_id}/review", api_review_get, methods=["GET"]),
        Route("/api/inputs/{input_id}/preview", input_preview),
        Route("/api/inputs/{input_id}/raw", input_raw),
        Route("/api/inputs/{input_id}/pdf_page", input_pdf_page),
        Route("/api/runs/{run_id}/artifacts/{artifact_id}/preview", artifact_preview),
        Route("/api/runs/{run_id}/artifacts/{artifact_id}/raw", artifact_raw),
        Route("/api/runs/{run_id}/artifacts/{artifact_id}/pdf_page", artifact_pdf_page),
        Route("/api/preview", generic_preview),
        Route("/api/preview/raw", generic_preview_raw),
        Route("/api/preview/pdf_page", generic_preview_pdf_page),
        Route("/api/runs/{run_id}/inspector", run_inspector),
        Route("/api/runs/{run_id}/diagnostics", run_diagnostics),
        Route("/api/runs/{run_id}/summary", run_summary),
        Route("/api/runs/compare", compare_runs_route),
        Route("/api/runs/{run_id}/artifacts/{artifact_id}", artifact_download),
        Route("/api/runs/{run_id}/artifacts/{artifact_path:path}", invalid_artifact_path),
        Route("/api/browse/files", browse_files, methods=["POST"]),
        Route("/api/browse/folder", browse_folder, methods=["POST"]),
        Route("/api/intake", intake, methods=["POST"]),
        Route("/api/review", review_post, methods=["POST"]),
        Route("/api/plan/preview", plan_preview, methods=["POST"]),
        Route("/api/runs", start_run, methods=["POST"]),
        Route("/api/runs/{run_id}/cancel", cancel_run, methods=["POST"]),
        Route("/api/runs/{run_id}/reveal", reveal_run, methods=["POST"]),
        Route("/api/history/clear", clear_history, methods=["POST"]),
        Route("/api/cache/clear", clear_cache, methods=["POST"]),
        Route("/api/{path:path}", api_not_found),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(LoopbackSecurityMiddleware)
    return app


__all__ = ["LoopbackSecurityMiddleware", "create_mukha_app"]
