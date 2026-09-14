"""Tests for Mukha protocol versioning and monotonic state revision tracking (Phase 3)."""

from __future__ import annotations

import json
import urllib.request
from typing import TYPE_CHECKING, Any

from sarathi.mukha.web.server import MukhaWebServer

if TYPE_CHECKING:
    pass


def _http_get(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, headers={"Host": "127.0.0.1"})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            status = resp.status
            data = resp.read()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            return status, data, headers
    except urllib.error.HTTPError as err:
        return err.code, err.read(), {k.lower(): v for k, v in err.headers.items()}


def _http_post(url: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Host": "127.0.0.1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def test_state_endpoint_includes_version_and_revision(web_server: MukhaWebServer) -> None:
    """GET /api/state response must contain schema_version and monotonic state_revision."""
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    assert res["schema_version"] == 1
    assert isinstance(res["state_revision"], int)
    assert res["state_revision"] >= 1
    # Check that state payload also has matching schema_version and state_revision
    assert res["state"]["schema_version"] == 1
    assert res["state"]["state_revision"] == res["state_revision"]


def test_state_revision_monotonic_increment(web_server: MukhaWebServer) -> None:
    """State revision must increase monotonically upon state-mutating actions."""
    r0 = web_server.runner.state_revision
    assert r0 >= 1

    from sarathi.sankalpa import Result, WarningRecord

    web_server.runner._last_result = Result(
        data=None,
        warnings=(
            WarningRecord(
                code="UNCERTAIN_GLYPH",
                message="Suspicious character",
                stage="ocr",
                context={"attempt_id": "att-ver-1"},
            ),
        ),
    )

    # Applying a review intent must increment revision
    status_post, res_post = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {
            "item_id": "rev-1",
            "attempt_id": "att-ver-1",
            "action_id": "accept",
        },
    )
    assert status_post == 200
    assert res_post["ok"] is True

    r1 = web_server.runner.state_revision
    assert r1 > r0

    # Query state again and verify returned revision equals r1
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["state_revision"] == r1


def test_sse_emits_schema_version_and_state_revision(web_server: MukhaWebServer) -> None:
    """SSE event stream must emit schema_version and state_revision in event payload."""
    url = f"http://127.0.0.1:{web_server.resolved_port}/api/events"
    req = urllib.request.Request(url, headers={"Host": "127.0.0.1"})

    with urllib.request.urlopen(req, timeout=5.0) as resp:
        # Read the initial event block
        lines = []
        for _ in range(5):
            line = resp.readline().decode("utf-8").strip()
            if line:
                lines.append(line)
            elif lines:
                break

    data_line = next((line for line in lines if line.startswith("data:")), None)
    assert data_line is not None
    payload = json.loads(data_line.removeprefix("data:").strip())
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert isinstance(payload["state_revision"], int)
    assert payload["state_revision"] >= 1
