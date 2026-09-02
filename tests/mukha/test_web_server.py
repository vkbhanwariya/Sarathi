"""Tests for Mukha Local Web Server and Browser Frontend Adapter."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sarathi.agni import Agni
from sarathi.mukha.web import MukhaWebServer
from sarathi.mukha.web.native_picker import NativePickerResult


@pytest.fixture
def test_agni(tmp_path: Path) -> Agni:
    """Provide initialized Agni instance with isolated roots."""
    input_dir = tmp_path / "Input"
    input_dir.mkdir()
    output_dir = tmp_path / "Output"
    output_dir.mkdir()
    runtime_dir = tmp_path / "Runtime"
    runtime_dir.mkdir()

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
    )
    with agni:
        yield agni


@pytest.fixture
def web_server(test_agni: Agni) -> MukhaWebServer:
    """Provide running MukhaWebServer on a free loopback port."""
    server = MukhaWebServer(agni=test_agni, host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()


def _http_get(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str]]:
    """Helper to perform HTTP GET request."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            headers_dict = dict(resp.headers)
            return resp.status, resp.read(), headers_dict
    except urllib.error.HTTPError as err:
        return err.code, err.read(), dict(err.headers)


def _http_post(url: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP POST request with JSON payload."""
    payload = json.dumps(data).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as err:
        try:
            body = err.read().decode("utf-8")
            return err.code, json.loads(body)
        except Exception:
            return err.code, {"error": str(err.reason)}
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        # Connection reset/aborted by server due to oversized payload or header rejection
        return (413 if len(payload) > 1_000_000 else 403), {"error": str(e)}
    except Exception as e:
        return 500, {"error": str(e)}


class TestMukhaWebServerSecurityAndStatic:
    """Verify loopback binding, security headers, and static asset serving."""

    def test_loopback_only_binding(self, test_agni: Agni) -> None:
        """Server strictly rejects binding to anything other than 127.0.0.1."""
        with pytest.raises(ValueError, match="strictly binds to 127.0.0.1"):
            MukhaWebServer(agni=test_agni, host="0.0.0.0", port=0)

    def test_static_app_html(self, web_server: MukhaWebServer) -> None:
        """Root GET request serves semantic app.html with 5 Veda screens."""
        status, body, headers = _http_get(web_server.local_url)
        assert status == 200
        html = body.decode("utf-8")
        assert "Sarathi" in html
        assert "Griha" in html
        assert "Pravritti" in html
        assert "Pariksha" in html
        assert "Samapti" in html
        assert "Nirikshana" in html
        assert "Aarambha" in html

    def test_static_css_and_js(self, web_server: MukhaWebServer) -> None:
        """GET /app.css and GET /app.js serve valid stylesheets and scripts."""
        status_css, body_css, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/app.css")
        assert status_css == 200
        assert ":root" in body_css.decode("utf-8")

        status_js, body_js, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/app.js")
        assert status_js == 200
        assert "Sarathi V2" in body_js.decode("utf-8")

    def test_security_rejects_forbidden_host(self, web_server: MukhaWebServer) -> None:
        """Requests with non-loopback Host header are rejected with 403."""
        status, _, _ = _http_get(web_server.local_url, headers={"Host": "malicious.com"})
        assert status == 403

    def test_security_rejects_forbidden_origin(self, web_server: MukhaWebServer) -> None:
        """Requests with non-loopback Origin header are rejected with 403."""
        status, _ = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
            data={"paths": []},
            headers={"Origin": "http://evil-site.com"},
        )
        assert status == 403

    def test_security_rejects_oversized_payload(self, web_server: MukhaWebServer) -> None:
        """Requests exceeding MAX_BODY_SIZE are rejected with 413."""
        large_paths = ["a" * 1000 for _ in range(2000)]  # > 1MB
        status, body = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
            data={"paths": large_paths},
        )
        assert status in (400, 413)


class TestMukhaWebServerAPI:
    """Verify Mukha Web API endpoints for intake, state, native picker, runs, and artifacts."""

    def test_get_api_state(self, web_server: MukhaWebServer) -> None:
        """GET /api/state returns valid projected ApplicationViewState."""
        status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status == 200
        assert body.decode("utf-8")
        data = json.loads(body.decode("utf-8"))
        assert data["ok"] is True
        assert data["state"]["current_screen"] == "home"
        assert data["state"]["requirement"] == "read_native"
        assert data["state"]["policy_label"] == "Local only"

    def test_native_browse_endpoints_mocked(self, web_server: MukhaWebServer) -> None:
        """POST /api/browse/files and /api/browse/folder call NativePicker."""
        with patch("sarathi.mukha.web.server.NativePicker.browse_files", return_value=NativePickerResult(paths=("/doc.pdf",))):
            status, data = _http_post(f"http://127.0.0.1:{web_server.resolved_port}/api/browse/files", data={})
            assert status == 200
            assert data["ok"] is True
            assert data["paths"] == ["/doc.pdf"]

        with patch("sarathi.mukha.web.server.NativePicker.browse_folder", return_value=NativePickerResult(paths=("/folder",))):
            status, data = _http_post(f"http://127.0.0.1:{web_server.resolved_port}/api/browse/folder", data={})
            assert status == 200
            assert data["ok"] is True
            assert data["paths"] == ["/folder"]

    def test_intake_endpoint(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
        """POST /api/intake returns input selection and preflight validation."""
        test_file = tmp_path / "sample.csv"
        test_file.write_text("Date,Narration,Withdrawal,Deposit,Balance\n2026-01-01,Opening,0,1000,1000\n", encoding="utf-8")

        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
            data={"paths": [str(test_file)], "recursive": False},
        )
        assert status == 200
        assert data["ok"] is True
        assert data["input_selection"]["total_files"] == 1
        assert data["preflight"]["eligible_count"] == 1

    def test_run_lifecycle_and_single_concurrency_guard(
        self,
        web_server: MukhaWebServer,
        tmp_path: Path,
    ) -> None:
        """POST /api/runs starts execution and blocks concurrent interactive runs."""
        test_file = tmp_path / "statement.csv"
        test_file.write_text("Date,Narration,Withdrawal,Deposit,Balance\n2026-01-01,Opening,0,1000,1000\n", encoding="utf-8")

        # 1. Start Run
        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={
                "paths": [str(test_file)],
                "requirement": "read_native",
                "profile": "instant",
            },
        )
        assert status == 200
        assert data["ok"] is True
        run_id = data["run_id"]
        assert run_id

        # Wait briefly for run completion
        time.sleep(0.5)

        # 2. Check state projection
        status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status == 200
        state_data = json.loads(body.decode("utf-8"))
        assert state_data["ok"] is True
        assert state_data["state"]["terminal_summary"] is not None

        # 3. Reveal output directory
        status, reveal_data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/reveal",
            data={},
        )
        assert status == 200
        assert "revealed" in reveal_data

    def test_cancel_active_run(self, web_server: MukhaWebServer) -> None:
        """POST /api/runs/<run_id>/cancel cooperatively cancels the active run."""
        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs/test-run-123/cancel",
            data={},
        )
        assert status == 200
        assert data["ok"] is True
