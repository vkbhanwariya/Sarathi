"""Static asset serving and Server-Sent Events (SSE) streaming for Mukha Web Server."""

from __future__ import annotations

import importlib.resources
import json
import socket
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from sarathi.mukha.web.security import _serialize_dataclass

if TYPE_CHECKING:
    from sarathi.mukha.web.http_handler import MukhaHTTPHandler


def serve_static_resource(handler: MukhaHTTPHandler, filename: str, content_type: str) -> None:
    """Serve packaged static asset using importlib.resources."""
    try:
        pkg = importlib.resources.files("sarathi.mukha.web")
        resource = pkg.joinpath(filename)
        content = resource.read_bytes()
    except Exception:
        local_path = Path(__file__).parent / filename
        if not local_path.is_file():
            handler.send_error(HTTPStatus.NOT_FOUND, f"Static resource {filename} missing.")
            return
        content = local_path.read_bytes()

    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler._apply_security_headers(cache_control="no-cache")
    handler.end_headers()
    handler.wfile.write(content)


def serve_asset_resource(handler: MukhaHTTPHandler, filename: str, content_type: str) -> None:
    """Serve packaged asset resource from sarathi.mukha.web.assets or disk."""
    try:
        pkg = importlib.resources.files("sarathi.mukha.web.assets")
        resource = pkg.joinpath(filename)
        content = resource.read_bytes()
    except Exception:
        local_path = Path(__file__).parent / "assets" / filename
        if not local_path.is_file():
            handler.send_error(HTTPStatus.NOT_FOUND, f"Asset {filename} not found.")
            return
        content = local_path.read_bytes()

    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(content)))
    handler._apply_security_headers(cache_control="public, max-age=3600")
    handler.end_headers()
    handler.wfile.write(content)


def serve_sse_stream(handler: MukhaHTTPHandler) -> None:
    """Stream real-time presentation state and progress events over Server-Sent Events (SSE)."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler._apply_security_headers(cache_control="no-cache")
    handler.end_headers()

    last_revision: int = -1
    last_serialized: str | None = None
    last_ping = time.time()

    try:
        while not getattr(handler.server, "_shutting_down", False):
            now = time.time()
            runner_rev = getattr(getattr(handler.mukha_app, "runner", None), "state_revision", None)
            app_state = handler.mukha_app.get_application_view_state()
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
                    handler.wfile.write(payload)
                    handler.wfile.flush()

            if now - last_ping >= 15.0:
                last_ping = now
                handler.wfile.write(b"event: ping\ndata: {}\n\n")
                handler.wfile.flush()

            time.sleep(0.5 if is_running else 1.5)
    except (ConnectionResetError, BrokenPipeError, socket.error, OSError):
        return
    except Exception:
        return
