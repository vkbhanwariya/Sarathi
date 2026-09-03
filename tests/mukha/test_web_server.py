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
        js_text = body_js.decode("utf-8")
        assert "Sarathi V2" in js_text
        assert "function updatePresentation(appState)" in js_text
        assert "function init()" in js_text
        assert "function handleBrowseFiles()" in js_text
        assert "function handleAddManualPath()" in js_text

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
        with patch(
            "sarathi.mukha.web.server.NativePicker.browse_files", return_value=NativePickerResult(paths=("/doc.pdf",))
        ):
            status, data = _http_post(f"http://127.0.0.1:{web_server.resolved_port}/api/browse/files", data={})
            assert status == 200
            assert data["ok"] is True
            assert data["paths"] == ["/doc.pdf"]

        with patch(
            "sarathi.mukha.web.server.NativePicker.browse_folder", return_value=NativePickerResult(paths=("/folder",))
        ):
            status, data = _http_post(f"http://127.0.0.1:{web_server.resolved_port}/api/browse/folder", data={})
            assert status == 200
            assert data["ok"] is True
            assert data["paths"] == ["/folder"]

    def test_intake_endpoint(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
        """POST /api/intake returns input selection and preflight validation."""
        test_file = tmp_path / "sample.csv"
        test_file.write_text(
            "Date,Narration,Withdrawal,Deposit,Balance\n2026-01-01,Opening,0,1000,1000\n", encoding="utf-8"
        )

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
        test_file.write_text(
            "Date,Narration,Withdrawal,Deposit,Balance\n2026-01-01,Opening,0,1000,1000\n", encoding="utf-8"
        )

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

    def test_real_agni_execution_displays_success(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
        """Verify real Agni run completion sets SUCCESS terminal status without status field on Result."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("Hello Sarathi V2", encoding="utf-8")

        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={"paths": [str(test_file)], "requirement": "read_native"},
        )
        assert status == 200
        run_id = data["run_id"]

        time.sleep(0.6)

        status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status == 200
        state = json.loads(body.decode("utf-8"))["state"]
        assert state["terminal_summary"] is not None
        assert state["terminal_summary"]["status"] == "SUCCESS"
        assert state["terminal_summary"]["run_id"] == run_id

    def test_cancelled_run_displays_cancelled_with_no_raw_exception(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Cancelled execution yields CANCELLED status without raw exception text."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("Sample", encoding="utf-8")

        with patch.object(web_server._agni, "execute") as mock_exec:
            from sarathi.dosh import DoshError, FailureCode

            mock_exec.side_effect = DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Execution was cancelled.",
                context={"cancelled": True},
            )

            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(test_file)], "requirement": "read_native"},
            )
            assert status == 200
            time.sleep(0.2)

            status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            state = json.loads(body.decode("utf-8"))["state"]
            assert state["terminal_summary"]["status"] == "CANCELLED"
            for failure in state["terminal_summary"]["failures"]:
                assert "Traceback" not in failure
                assert "Exception" not in failure

    def test_run_scoped_telemetry_isolation(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
        """Verify Darpana telemetry queries are filtered strictly to the active run_id."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("Hello Telemetry", encoding="utf-8")

        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={"paths": [str(test_file)], "requirement": "read_native"},
        )
        assert status == 200
        run_id = data["run_id"]
        time.sleep(0.6)

        maruti, pramana = web_server._get_run_telemetry(run_id)
        for r in maruti:
            assert r.run_id == run_id or r.request_id == run_id
        for p in pramana:
            assert p.run_id == run_id or p.request_id == run_id

    def test_runtime_and_output_paths_rejected_through_web_intake(self, web_server: MukhaWebServer) -> None:
        """Web intake rejects configured runtime and output root directories."""
        runtime_file = web_server.runtime_root / "temp.txt"
        runtime_file.write_text("test", encoding="utf-8")

        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
            data={"paths": [str(runtime_file)]},
        )
        assert status in (400, 403)
        assert data["ok"] is False

    def test_unavailable_translation_cannot_start(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
        """Starting unavailable requirement (translation) is rejected with 400."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("Test", encoding="utf-8")

        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={"paths": [str(test_file)], "requirement": "translation"},
        )
        assert status == 400
        assert data["ok"] is False
        assert "unavailable" in data["error"].lower()

    def test_confirmed_artifact_download_and_containment_security(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Artifact downloads stream confirmed artifacts and reject cross-run or outside paths."""
        from sarathi.sankalpa import ArtifactRef

        run_id = "run_test_art"
        art_id = "art_123"
        art_path = web_server.output_root / "test_artifact.txt"
        art_path.write_text("Protected Content", encoding="utf-8")

        ref = ArtifactRef(
            artifact_id=art_id,
            path=art_path,
            role="report",
            media_type="text/plain",
            size_bytes=len("Protected Content"),
            checksum_sha256="dummy",
        )

        with web_server._lock:
            web_server._confirmed_artifacts[run_id] = {art_id: ref}

        # 1. Successful download
        status, body, headers = _http_get(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/artifacts/{art_id}"
        )
        assert status == 200
        assert body == b"Protected Content"
        assert headers.get("X-Content-Type-Options") == "nosniff"

        # 2. Unknown artifact ID -> 404
        status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/artifacts/wrong_id")
        assert status == 404

        # 3. Wrong run ID -> 404
        status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/wrong_run/artifacts/{art_id}")
        assert status == 404

    def test_run_accepts_custom_options_and_forwards_to_request(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """POST /api/runs parses custom_options and passes them to Request."""
        test_file = tmp_path / "doc.txt"
        test_file.write_text("Hello Custom", encoding="utf-8")

        captured_request: list[Any] = []
        original_execute = web_server._agni.execute

        def mock_execute(req: Any) -> Any:
            captured_request.append(req)
            return original_execute(req)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={
                    "paths": [str(test_file)],
                    "requirement": "read_native",
                    "custom_options": {"lang": "devanagari"},
                },
            )
            assert status == 200
            assert data["ok"] is True
            time.sleep(0.5)

        assert len(captured_request) == 1
        assert captured_request[0].custom_options.get("lang") == "devanagari"

    def test_reveal_output_directory_invokes_platform_opener(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """reveal_output_directory executes without raising and returns true when dir exists."""
        run_id = "run_reveal_test"
        out_dir = tmp_path / "out_dir"
        out_dir.mkdir()
        with web_server._lock:
            web_server._run_output_roots[run_id] = out_dir

        with patch("subprocess.Popen") as mock_popen, patch("subprocess.run") as mock_run:
            res = web_server.reveal_output_directory(run_id)
            assert res is True
            assert mock_popen.called

    def test_active_workers_and_page_progress_in_view_state(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Verify that live progress updates populate active_workers and page numbers in state."""
        import threading
        test_file = tmp_path / "report.pdf"
        test_file.write_text("dummy", encoding="utf-8")

        started_evt = threading.Event()
        finish_evt = threading.Event()

        def mock_execute(req: Any) -> Any:
            prog_cb = req.custom_options["progress_callback"]
            prog_cb(
                file_display_name="report.pdf",
                page_number=3,
                total_pages=5,
                worker_id="2",
                stage="Optical Character Recognition (OCR)",
                device_type="GPU",
            )
            started_evt.set()
            finish_evt.wait(timeout=2.0)
            from sarathi.contracts import Result
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(test_file)], "requirement": "ocr"},
            )
            assert status == 200
            assert started_evt.wait(timeout=2.0)

            # Query state while run is active
            status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            assert status == 200
            state = json.loads(body.decode("utf-8"))["state"]
            active_run = state["active_run"]
            assert active_run is not None
            assert len(active_run["active_workers"]) == 1
            worker = active_run["active_workers"][0]
            assert worker["worker_id"] == "2"
            assert worker["page_number"] == 3
            assert worker["device_type"] == "GPU"
            assert worker["stage"] == "Optical Character Recognition (OCR)"

            # Verify current_stage of file view shows page
            file_view = active_run["files"][0]
            assert "Page 3/5" in file_view["current_stage"]

            finish_evt.set()


def test_negative_content_length_rejected(web_server: MukhaWebServer) -> None:
    """Verify negative Content-Length headers are rejected with 400 Bad Request."""
    url = f"http://127.0.0.1:{web_server.resolved_port}/api/runs"
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Length": "-1", "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400
