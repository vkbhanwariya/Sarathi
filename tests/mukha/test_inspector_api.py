"""Tests for Nirikshana Inspector API endpoint and presentation projection."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sarathi.mukha.web import MukhaWebServer
from sarathi.sankalpa import Result


def _http_get(url: str) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP GET returning JSON."""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"error": str(err.reason)}
        return err.code, parsed


def _http_post(url: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP POST returning JSON."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body)


class TestInspectorApi:
    """Verify GET /api/runs/<run_id>/inspector behavior, security, and log projection."""

    def test_inspector_endpoint_returns_200_for_run(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """GET /api/runs/<run_id>/inspector returns 200 with structured inspector state."""
        f1 = tmp_path / "doc.txt"
        f1.write_text("Hello Inspector", encoding="utf-8")

        def mock_execute(req: Any) -> Any:
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert status == 200
            run_id = data["run_id"]
            time.sleep(0.5)

            # Query inspector endpoint
            status, insp_data = _http_get(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/inspector"
            )
            assert status == 200
            assert insp_data["ok"] is True
            inspector = insp_data["inspector"]
            assert inspector["run_id"] == run_id
            assert "activity_logs" in inspector
            assert "device_summaries" in inspector
            assert "stage_timings" in inspector
            assert "system_facts" in inspector

    def test_inspector_endpoint_rejects_invalid_id(
        self, web_server: MukhaWebServer
    ) -> None:
        """Inspector endpoint rejects path traversal or invalid characters with 400."""
        status, _ = _http_get(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs/bad..id/inspector"
        )
        assert status == 400

    def test_inspector_endpoint_404_for_unknown_run(
        self, web_server: MukhaWebServer
    ) -> None:
        """Inspector endpoint returns 404 for non-existent run ID."""
        status, _ = _http_get(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs/run_nonexistent_999/inspector"
        )
        assert status == 404
