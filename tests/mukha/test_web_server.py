"""Tests for Mukha Local Web Server and Browser Frontend Adapter."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sarathi.agni import Agni
from sarathi.mukha.web import MukhaWebServer
from sarathi.mukha.web.native_picker import NativePickerResult
from sarathi.sankalpa import Result, WarningRecord
from tests.mukha.conftest import _http_get, _http_post, _wait_for_idle


class TestMukhaWebServerSecurityAndStatic:
    """Verify loopback binding, security headers, and static asset serving."""

    def test_loopback_only_binding(self, test_agni: Agni) -> None:
        """Server strictly rejects binding to anything other than 127.0.0.1."""
        with pytest.raises(ValueError, match="strictly binds to 127.0.0.1"):
            MukhaWebServer(agni=test_agni, host="0.0.0.0", port=0)

    def test_static_app_html(self, web_server: MukhaWebServer) -> None:
        """Root GET request serves Preact index."""
        status, body, headers = _http_get(web_server.local_url)
        assert status == 200
        html = body.decode("utf-8")
        assert "Sarathi" in html
        assert 'id="app"' in html
        assert "/ui/app.js" in html

    def test_static_css_and_js(self, web_server: MukhaWebServer) -> None:
        """GET /ui/app.css and GET /ui/app.js serve valid stylesheets and scripts."""
        status_css, body_css, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.css")
        assert status_css == 200
        assert ":root" in body_css.decode("utf-8")

        status_js, body_js, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.js")
        assert status_js == 200
        js_text = body_js.decode("utf-8")
        assert "Sarathi" in js_text

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
        """Requests exceeding MAX_BODY_SIZE are rejected with 413 or early socket closure."""
        large_paths = ["a" * 1000 for _ in range(2000)]  # > 1MB
        try:
            status, body = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
                data={"paths": large_paths},
            )
            assert status in (400, 413)
        except AssertionError as exc:
            # On Windows, early server socket closure on 413 aborts client send
            assert isinstance(exc.__cause__, (ConnectionResetError, ConnectionAbortedError)) or any(
                term in str(exc)
                for term in ("10053", "10054", "ConnectionAbortedError", "ConnectionResetError", "forcibly closed")
            )


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
            "sarathi.mukha.web.app.NativePicker.browse_files", return_value=NativePickerResult(paths=("/doc.pdf",))
        ):
            status, data = _http_post(f"http://127.0.0.1:{web_server.resolved_port}/api/browse/files", data={})
            assert status == 200
            assert data["ok"] is True
            assert data["paths"] == ["/doc.pdf"]

        with patch(
            "sarathi.mukha.web.app.NativePicker.browse_folder", return_value=NativePickerResult(paths=("/folder",))
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

    def test_intake_rescan_endpoint(
        self,
        web_server: MukhaWebServer,
    ) -> None:
        """POST /api/intake/rescan discovers newly added files in input_root."""
        new_file = web_server.input_root / "rescan_test.txt"
        new_file.write_text("Rescan test content", encoding="utf-8")
        try:
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/intake/rescan",
                data={},
            )
            assert status == 200
            assert data["ok"] is True
            assert data["input_selection"] is not None
            names = [it["display_name"] for it in data["input_selection"]["items"]]
            assert "rescan_test.txt" in names
        finally:
            if new_file.is_file():
                new_file.unlink()

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
        _wait_for_idle(web_server)

        # 2. Check state projection
        status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status == 200
        state_data = json.loads(body.decode("utf-8"))
        assert state_data["ok"] is True
        assert state_data["state"]["terminal_summary"] is not None

        output_dirs = list((web_server.output_root / "read_native").glob("Run-*"))
        assert len(output_dirs) == 1
        assert (output_dirs[0] / "run-manifest.json").is_file()

        # 3. Exercise reveal routing without launching a file manager or changing focus.
        with patch("sarathi.mukha.web.runner.subprocess") as mock_subprocess:
            status, reveal_data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/reveal",
                data={},
            )
            assert mock_subprocess.Popen.called
            assert mock_subprocess.Popen.call_args.args[0][1:] == [str(output_dirs[0])]

        assert status == 200
        assert reveal_data["revealed"] is True

    def test_consecutive_runs_intake_retention_and_execution(
        self,
        web_server: MukhaWebServer,
        tmp_path: Path,
    ) -> None:
        """Verify that multiple consecutive runs with different intake files execute cleanly without server restart."""
        doc1 = tmp_path / "doc1.txt"
        doc1.write_text("First document contents.", encoding="utf-8")
        doc2 = tmp_path / "doc2.txt"
        doc2.write_text("Second document contents.", encoding="utf-8")

        # 1. Intake doc1
        status1, intake1 = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
            data={"paths": [str(doc1)], "recursive": False},
        )
        assert status1 == 200
        assert intake1["ok"] is True
        assert intake1["input_selection"]["total_files"] == 1
        assert intake1["input_selection"]["items"][0]["display_name"] == "doc1.txt"

        # State should project doc1
        status_st1, body_st1, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status_st1 == 200
        st1 = json.loads(body_st1.decode("utf-8"))["state"]
        assert st1["input_selection"]["total_files"] == 1
        assert st1["input_selection"]["items"][0]["display_name"] == "doc1.txt"

        # 2. Run 1 execution
        status_run1, run1_data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={
                "paths": [str(doc1)],
                "requirement": "read_native",
                "profile": "instant",
            },
        )
        assert status_run1 == 200
        assert run1_data["ok"] is True
        _wait_for_idle(web_server)

        # Confirm Run 1 has terminated and runner is ready for a new run
        assert not web_server.runner.is_busy()
        assert web_server.runner.get_active_snapshot().is_alive is False

        # 3. Intake doc2 for Run 2 without restarting server
        status2, intake2 = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
            data={"paths": [str(doc2)], "recursive": False},
        )
        assert status2 == 200
        assert intake2["ok"] is True
        assert intake2["input_selection"]["total_files"] == 1
        assert intake2["input_selection"]["items"][0]["display_name"] == "doc2.txt"

        # State projection must reflect doc2, NOT lingering doc1 from previous run
        status_st2, body_st2, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status_st2 == 200
        st2 = json.loads(body_st2.decode("utf-8"))["state"]
        assert st2["input_selection"]["total_files"] == 1
        assert st2["input_selection"]["items"][0]["display_name"] == "doc2.txt"
        assert st2["preflight"] is not None
        assert st2["preflight"]["eligible_count"] == 1

        # 4. Start Run 2 with doc2 - must succeed without "run already active" error
        status_run2, run2_data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={
                "paths": [str(doc2)],
                "requirement": "read_native",
                "profile": "instant",
            },
        )
        assert status_run2 == 200
        assert run2_data["ok"] is True
        assert run2_data["run_id"] != run1_data["run_id"]
        _wait_for_idle(web_server)

        # Confirm Run 2 terminal summary
        assert not web_server.runner.is_busy()
        status_st3, body_st3, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status_st3 == 200
        st3 = json.loads(body_st3.decode("utf-8"))["state"]
        assert st3["terminal_summary"]["run_id"] == run2_data["run_id"]

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
        test_file.write_text("Hello Sarathi", encoding="utf-8")

        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={"paths": [str(test_file)], "requirement": "read_native"},
        )
        assert status == 200
        run_id = data["run_id"]
        _wait_for_idle(web_server)

        status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
        assert status == 200
        state = json.loads(body.decode("utf-8"))["state"]
        assert state["terminal_summary"] is not None
        assert state["terminal_summary"]["status"] == "SUCCESS"
        assert state["terminal_summary"]["run_id"] == run_id

    def test_cached_run_telemetry_and_summary_badge(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
        """Verify cached run execution properly reflects cached: True on summary and file progress."""
        from sarathi.sankalpa import Result

        test_file = tmp_path / "cached_doc.txt"
        test_file.write_text("Hello Cached", encoding="utf-8")

        mock_result = Result(
            data=None,
            metadata={"cached": True, "cached_capabilities": ["read_native"]},
        )
        with patch.object(web_server.agni, "execute", return_value=mock_result):
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(test_file)], "requirement": "read_native"},
            )
            assert status == 200
            run_id = data["run_id"]
            _wait_for_idle(web_server)

            status_st, body_st, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            assert status_st == 200
            state = json.loads(body_st.decode("utf-8"))["state"]
            assert state["terminal_summary"] is not None
            assert state["terminal_summary"]["run_id"] == run_id
            assert state["terminal_summary"]["cached"] is True
            assert state["active_run"] is not None
            assert any(f.get("cached") is True for f in state["active_run"]["files"])

    def test_cancelled_run_displays_cancelled_with_no_raw_exception(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Cancelled execution yields CANCELLED status without raw exception text."""
        test_file = tmp_path / "data.txt"
        test_file.write_text("Sample", encoding="utf-8")

        with patch.object(web_server.agni, "execute") as mock_exec:
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
            _wait_for_idle(web_server)

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
        _wait_for_idle(web_server)

        from sarathi.mukha.web.state_builder import get_run_telemetry

        maruti, pramana = get_run_telemetry(web_server.agni, run_id)
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
        from sarathi.sankalpa import CapabilityReadiness, ReadinessStatus

        test_file = tmp_path / "data.txt"
        test_file.write_text("Test", encoding="utf-8")

        unavail = {
            "translation": CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="Models unavailable",
            )
        }
        with patch.object(web_server.agni, "audit_readiness", return_value=unavail):
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
        """Artifact downloads stream confirmed artifacts and reject cross-run lookup."""
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

        def confirmed_artifact(candidate_run_id: str, candidate_artifact_id: str):
            if candidate_run_id == run_id and candidate_artifact_id == art_id:
                return ref
            return None

        with patch.object(web_server, "get_confirmed_artifact", side_effect=confirmed_artifact):
            status, body, headers = _http_get(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/artifacts/{art_id}"
            )
            assert status == 200
            assert body == b"Protected Content"
            assert headers.get("X-Content-Type-Options") == "nosniff"

            status, _, _ = _http_get(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/artifacts/wrong_id"
            )
            assert status == 404
            status, _, _ = _http_get(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/wrong_run/artifacts/{art_id}"
            )
            assert status == 404

        # Outside containment returns 403 Forbidden
        outside_file = tmp_path / "outside_forbidden" / "secret.txt"
        outside_file.parent.mkdir(parents=True, exist_ok=True)
        outside_file.write_text("secret", encoding="utf-8")
        leak_ref = ArtifactRef(
            artifact_id="art_leak",
            path=outside_file,
            role="report",
            media_type="text/plain",
            size_bytes=6,
        )
        with patch.object(web_server, "get_confirmed_artifact", return_value=leak_ref):
            status, _, _ = _http_get(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/artifacts/art_leak"
            )
            assert status == 403

    def test_run_accepts_custom_options_and_forwards_to_request(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """POST /api/runs parses custom_options and passes them to Request."""
        test_file = tmp_path / "doc.txt"
        test_file.write_text("Hello Custom", encoding="utf-8")

        captured_request: list[Any] = []
        original_execute = web_server.agni.execute

        def mock_execute(req: Any) -> Any:
            captured_request.append(req)
            return original_execute(req)

        with patch.object(web_server.agni, "execute", side_effect=mock_execute):
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
            _wait_for_idle(web_server)

        assert len(captured_request) == 1
        assert captured_request[0].custom_options.get("lang") == "devanagari"

    def test_reveal_output_directory_delegates_to_runner(self, web_server: MukhaWebServer) -> None:
        """The web façade delegates output reveal to the run coordinator."""
        run_id = "run_reveal_test"
        with patch.object(web_server.runner, "reveal_output_directory", return_value=True) as reveal:
            assert web_server.reveal_output_directory(run_id) is True
        reveal.assert_called_once_with(run_id)

    def test_active_workers_and_page_progress_in_view_state(self, web_server: MukhaWebServer, tmp_path: Path) -> None:
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
            from sarathi.sankalpa import Result

            return Result(data=None)

        with (
            patch.object(web_server.agni, "execute", side_effect=mock_execute),
            patch(
                "sarathi.mukha.presenter.MukhaPresenter.audit_capability_status", return_value={"ocr": (True, "Ready")}
            ),
        ):
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
            _wait_for_idle(web_server)


def test_negative_content_length_rejected(web_server: MukhaWebServer) -> None:
    """Verify negative Content-Length headers are rejected with 400 Bad Request."""
    url = f"http://127.0.0.1:{web_server.resolved_port}/api/runs"
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Length": "-1", "Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 400


def test_serialize_dataclass_with_value_field() -> None:
    """Dataclasses with a field named 'value' must not be mistaken for Enums (F-01)."""
    from dataclasses import dataclass
    from enum import Enum

    from sarathi.mukha.web.security import _serialize_dataclass

    class StatusEnum(Enum):
        ACTIVE = "active"

    @dataclass
    class CustomMetric:
        name: str
        value: float
        status: StatusEnum

    metric = CustomMetric(name="speed", value=99.5, status=StatusEnum.ACTIVE)
    serialized = _serialize_dataclass(metric)

    assert isinstance(serialized, dict)
    assert serialized["name"] == "speed"
    assert serialized["value"] == 99.5
    assert serialized["status"] == "active"


def test_format_public_error_strips_paths() -> None:
    """DoshError messages containing filesystem paths must have paths redacted (F-02, F-04)."""
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.mukha.web.server import _format_public_error

    err_win = DoshError(
        code=FailureCode.EXECUTION_FAILED,
        message="Cannot open file C:\\Users\\Administrator\\Secret\\doc.pdf for processing.",
    )
    formatted_win = _format_public_error(err_win)
    assert "C:\\Users" not in formatted_win
    assert "[path]" in formatted_win
    assert "EXECUTION_FAILED" in formatted_win

    err_posix = DoshError(
        code=FailureCode.SECURITY_DENIED,
        message="Access denied to /var/secrets/key.pem from client.",
    )
    formatted_posix = _format_public_error(err_posix)
    assert "/var/secrets" not in formatted_posix
    assert "[path]" in formatted_posix
    assert "SECURITY_DENIED" in formatted_posix

    # UNC paths and paths with spaces
    err_unc = DoshError(
        code=FailureCode.EXECUTION_FAILED,
        message="Network error accessing \\\\fileserver\\shared\\data\\report.csv timeout.",
    )
    formatted_unc = _format_public_error(err_unc)
    assert "\\\\fileserver" not in formatted_unc
    assert "[path]" in formatted_unc

    err_quoted = DoshError(
        code=FailureCode.INVALID_CONFIGURATION,
        message="Missing config file 'C:\\Program Files\\Sarathi\\config.json' from host.",
    )
    formatted_quoted = _format_public_error(err_quoted)
    assert "C:\\Program Files" not in formatted_quoted
    assert "[path]" in formatted_quoted

    err_spaces = DoshError(
        code=FailureCode.EXECUTION_FAILED,
        message="Failed reading C:\\Users\\John Doe\\Secret Files\\doc.txt, aborting.",
    )
    formatted_spaces = _format_public_error(err_spaces)
    assert "C:\\Users" not in formatted_spaces
    assert "[path]" in formatted_spaces


def test_artifact_endpoint_rejects_path_traversal(web_server: MukhaWebServer) -> None:
    """Artifact download endpoint must reject traversal and malformed IDs (F-16)."""
    # 1. Path traversal in artifact_id -> 400
    status, _, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/runs/run123/artifacts/..%2F..%2Fsecret.txt"
    )
    assert status == 400

    # 2. Invalid characters in run_id -> 400
    status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/bad!id/artifacts/art123")
    assert status == 400


def test_api_history_endpoint(web_server: MukhaWebServer) -> None:
    """F37: GET /api/history returns valid history list."""
    status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/history")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["ok"] is True
    assert "history" in data
    assert isinstance(data["history"], list)


def test_api_clear_history_and_cache_endpoints(web_server: MukhaWebServer) -> None:
    """Test POST /api/history/clear and POST /api/cache/clear endpoints."""
    # 1. Clear history
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/history/clear",
        {},
    )
    assert status == 200
    assert resp.get("ok") is True
    assert resp.get("cleared") is True

    # 2. Clear cache
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/cache/clear",
        {},
    )
    assert status == 200
    assert resp.get("ok") is True
    assert "cleared_entries" in resp


def test_api_review_endpoints(web_server: MukhaWebServer) -> None:
    from sarathi.sankalpa import Result, WarningRecord

    web_server.runner._last_result = Result(
        data=None,
        warnings=(
            WarningRecord(
                code="UNCERTAIN_GLYPH",
                message="Suspicious character",
                stage="ocr",
                context={"source": "a", "output": "b", "attempt_id": "att-test-1"},
            ),
        ),
    )

    # 1. GET /api/review
    status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["ok"] is True
    assert len(data["items"]) == 1
    assert data["items"][0]["attempt_id"] == "att-test-1"

    # 2. POST /api/review without attempt_id -> 400 (no fabricated att-1)
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": "rev-1", "action": "accept"},
    )
    assert status == 400
    assert resp["ok"] is False

    # 3. POST /api/review with valid attempt_id and supported action 'accept'
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": "rev-1", "attempt_id": "att-test-1", "action": "accept"},
    )
    assert status == 200
    assert resp["ok"] is True
    assert resp["action"] == "accept"

    # 4. POST /api/review with invalid action -> 400
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": "rev-1", "attempt_id": "att-test-1", "action": "invalid_action"},
    )
    assert status == 400
    assert resp["ok"] is False


def test_warning_without_context_attempt_id_generates_actionable_review_item(web_server: MukhaWebServer) -> None:
    """Warnings without span_id or context attempt_id receive deterministic attempt_id and can be accepted."""
    from sarathi.sankalpa import Result, WarningRecord

    web_server.runner._last_result = Result(
        data=None,
        warnings=(
            WarningRecord(code="GENERIC_WARN", message="General warning without context", stage="native_extraction"),
        ),
    )
    web_server.runner._last_result_run_id = "run-test-det"

    # GET /api/review should produce a non-empty attempt_id
    status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["ok"] is True
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["item_id"] == "rev-1"
    assert item["attempt_id"] != ""
    assert item["attempt_id"].startswith("att-")

    # POST /api/review with the generated attempt_id must succeed
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": item["item_id"], "attempt_id": item["attempt_id"], "action": "accept"},
    )
    assert status == 200
    assert resp["ok"] is True
    assert resp["action"] == "accept"


def test_operational_warnings_excluded_from_review_queue(web_server: MukhaWebServer) -> None:
    """Operational/infrastructure warnings like OCR_FALLBACK_UNAVAILABLE must never appear in Review queue."""
    from sarathi.sankalpa import Result, WarningRecord

    # Case 1: Pure operational warnings
    web_server.runner._last_result = Result(
        data=None,
        warnings=(
            WarningRecord(
                code="OCR_FALLBACK_UNAVAILABLE",
                message="NE-OCR fallback engine is not available on this host.",
                stage="ocr",
            ),
            WarningRecord(
                code="CALAMINE_FALLBACK",
                message="Fallback to calamine reader.",
                stage="native_extraction",
            ),
        ),
    )
    web_server.runner._last_result_run_id = "run-test-op-only"

    status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["ok"] is True
    assert len(data["items"]) == 0, "Operational warnings must not pollute the human review queue"

    # Also verify ApplicationViewState.review_queue is empty
    app_state = web_server.get_application_view_state()
    assert len(app_state.review_queue) == 0

    # Case 2: Mixed warnings (operational + genuine content review)
    web_server.runner._last_result = Result(
        data=None,
        warnings=(
            WarningRecord(
                code="OCR_FALLBACK_UNAVAILABLE",
                message="NE-OCR fallback engine is not available on this host.",
                stage="ocr",
            ),
            WarningRecord(
                code="UNCERTAIN_GLYPH",
                message="Suspicious character detected",
                stage="ocr",
                context={"source": "1O0", "output": "100", "attempt_id": "span-low-conf"},
            ),
        ),
    )
    web_server.runner._last_result_run_id = "run-test-mixed"

    status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["ok"] is True
    assert len(data["items"]) == 1
    assert data["items"][0]["item_id"] == "rev-2"
    assert data["items"][0]["code"] == "UNCERTAIN_GLYPH"
    assert data["items"][0]["attempt_id"] == "span-low-conf"

    # POST review intent for the content review item must succeed
    status_post, resp_post = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": "rev-2", "attempt_id": "span-low-conf", "action": "accept"},
    )
    assert status_post == 200
    assert resp_post["ok"] is True
    assert resp_post["action"] == "accept"


def test_accepting_second_review_item_does_not_accept_first_item(web_server: MukhaWebServer) -> None:
    """Verify accepting one review item does NOT falsely mark preceding review items as accepted."""
    web_server.runner._last_result = Result(
        data="dummy",
        warnings=(
            WarningRecord(
                code="OCR_FALLBACK_UNAVAILABLE",
                message="Operational warning",
                stage="ocr",
            ),
            WarningRecord(
                code="UNCERTAIN_GLYPH",
                message="Suspicious character 1",
                stage="ocr",
                context={"attempt_id": "att-warn-2"},
            ),
            WarningRecord(
                code="UNCERTAIN_GLYPH",
                message="Suspicious character 2",
                stage="ocr",
                context={"attempt_id": "att-warn-3"},
            ),
        ),
    )
    web_server.runner._last_result_run_id = "run-test-isolation"

    status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert len(data["items"]) == 2
    assert data["items"][0]["item_id"] == "rev-2"
    assert data["items"][1]["item_id"] == "rev-3"

    # Accept only the second displayed review item (rev-3)
    status_post, resp_post = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": "rev-3", "attempt_id": "att-warn-3", "action": "accept"},
    )
    assert status_post == 200
    assert resp_post["ok"] is True

    # Re-fetch review items: rev-2 must be PENDING, rev-3 must be ACCEPTED
    status2, body2, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status2 == 200
    data2 = json.loads(body2.decode("utf-8"))
    assert data2["items"][0]["item_id"] == "rev-2"
    assert data2["items"][0]["status"] == "pending"
    assert data2["items"][1]["item_id"] == "rev-3"
    assert data2["items"][1]["status"] == "accepted"



def test_api_payload_validation_rejects_malformed(web_server: MukhaWebServer) -> None:
    """F36: POST /api/runs and /api/intake reject malformed types with 400 Bad Request."""
    # Non-boolean recursive
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
        {"paths": ["some_file.pdf"], "recursive": "not_a_bool"},
    )
    assert status == 400
    assert resp["ok"] is False

    # Empty or non-list paths
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
        {"paths": "not_a_list"},
    )
    assert status == 400
    assert resp["ok"] is False

    # Invalid profile
    status, resp = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
        {"paths": ["valid.pdf"], "profile": "non_existent_profile"},
    )
    assert status == 400
    assert resp["ok"] is False

    # Plan preview with invalid profile -> 400 (no silent fallback to instant)
    status_prev_prof, resp_prev_prof = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/plan/preview",
        {"paths": ["valid.pdf"], "profile": "invalid_profile_name"},
    )
    assert status_prev_prof == 400
    assert resp_prev_prof["ok"] is False

    # Plan preview with non-boolean recursive -> 400 (no silent string coercion)
    status_prev_rec, resp_prev_rec = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/plan/preview",
        {"paths": ["valid.pdf"], "recursive": "false_as_string"},
    )
    assert status_prev_rec == 400
    assert resp_prev_rec["ok"] is False


def test_static_assets_serving(web_server: MukhaWebServer) -> None:
    """GET /assets/icons.svg serves SVG icon sprites from assets package."""
    status, body, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/assets/icons.svg")
    assert status == 200
    assert b"<svg" in body
    assert b"icon-file" in body


def test_api_events_sse(web_server: MukhaWebServer) -> None:
    """GET /api/events establishes text/event-stream with initial state event."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{web_server.resolved_port}/api/events",
        headers={"Cookie": f"sarathi_session={web_server.auth_token}"},
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/event-stream" in content_type
        line1 = resp.readline().decode("utf-8")
        line2 = resp.readline().decode("utf-8")
        assert "event: state" in line1 or "event: ping" in line1 or "data:" in line1 or "data:" in line2


def test_api_preview_text_and_tabular(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """GET /api/preview serves structured text and tabular CSV previews."""
    # Text file
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("Hello Sarathi Modern Web!", encoding="utf-8")
    status, data, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path={urllib.parse.quote(str(txt_file))}"
    )
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    assert res["type"] == "text"
    assert "Hello Sarathi" in res["content"]

    # Tabular CSV file
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("col1,col2\nval1,val2\nval3,val4\n", encoding="utf-8")
    status_csv, data_csv, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path={urllib.parse.quote(str(csv_file))}"
    )
    assert status_csv == 200
    res_csv = json.loads(data_csv.decode("utf-8"))
    assert res_csv["ok"] is True
    assert res_csv["type"] == "tabular"
    assert res_csv["headers"] == ["col1", "col2"]
    assert len(res_csv["rows"]) == 2


def test_api_preview_traversal_rejected(web_server: MukhaWebServer) -> None:
    """GET /api/preview rejects directory traversal attempts and sensitive system paths."""
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path=../../etc/passwd")
    assert status == 400
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is False

    # Direct system path -> 403 Forbidden
    status_sys, data_sys, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path=/etc/shadow")
    assert status_sys == 403
    res_sys = json.loads(data_sys.decode("utf-8"))
    assert res_sys["ok"] is False


def test_api_review_intent_workflow(web_server: MukhaWebServer) -> None:
    """POST /api/review records ReviewIntent with truthful statuses without overwriting committed output."""
    from sarathi.sankalpa import Result, WarningRecord

    # Inject mock warning result
    web_server.runner._last_result = Result(
        data=None,
        warnings=(
            WarningRecord(
                code="UNCERTAIN_GLYPH",
                message="Suspicious character",
                stage="ocr",
                context={"source": "vkn", "output": "vkd", "attempt_id": "span-42"},
            ),
        ),
    )

    # 1. Verify pending review item
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status == 200
    items = json.loads(data.decode("utf-8"))["items"]
    assert len(items) == 1
    assert items[0]["item_id"] == "rev-1"
    assert items[0]["status"] == "pending"
    assert items[0]["attempt_id"] == "span-42"
    assert items[0]["available_actions"] == ["accept", "unresolved"]

    # 2. Reject unsupported action validate_edit (capability validation not yet in runtime)
    status_edit, res_edit = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {
            "item_id": "rev-1",
            "attempt_id": "span-42",
            "action_id": "validate_edit",
            "proposed_value": "vkb",
        },
    )
    assert status_edit == 400
    assert res_edit["ok"] is False

    # 3. Submit supported 'unresolved' action
    status_post, res_post = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {
            "item_id": "rev-1",
            "attempt_id": "span-42",
            "action_id": "unresolved",
        },
    )
    assert status_post == 200
    assert res_post["ok"] is True
    assert res_post["action"] == "unresolved"
    assert res_post["applied"] is True

    # 4. Query review items again: status is 'unresolved', NOT 'resolved', and output is unaltered
    status2, data2, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/review")
    assert status2 == 200
    items2 = json.loads(data2.decode("utf-8"))["items"]
    assert len(items2) == 1
    assert items2[0]["status"] == "unresolved"
    assert items2[0]["applied_action"] == "unresolved"
    assert items2[0]["context"]["output"] == "vkd"


def test_scoped_input_and_artifact_preview(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """Scoped preview endpoints reject non-existent IDs and serve authorized content."""
    # 404 for unknown input ID
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/inputs/nonexistent-id/preview")
    assert status == 404
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is False

    # 404 for unknown artifact ID
    status_art, data_art, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/runs/run-mock/artifacts/art-mock/preview"
    )
    assert status_art == 404


def test_intake_preview_by_input_id(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """Verify documents added via intake can be previewed by input_id before starting a run."""
    doc_file = tmp_path / "sample_doc.txt"
    doc_file.write_text("Hello Sarathi Preview!", encoding="utf-8")

    # 1. Intake document
    intake_status, intake_res = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/intake",
        {"paths": [str(doc_file)], "recursive": False},
    )
    assert intake_status == 200
    assert intake_res["ok"] is True
    items = intake_res["input_selection"]["items"]
    assert len(items) >= 1
    input_id = items[0]["input_id"]

    # 2. Preview document via /api/inputs/<input_id>/preview
    prev_status, prev_data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/inputs/{input_id}/preview")
    assert prev_status == 200
    prev_payload = json.loads(prev_data.decode("utf-8"))
    assert prev_payload["ok"] is True
    assert prev_payload["type"] == "text"
    assert "Hello Sarathi Preview!" in prev_payload["content"]


def test_get_run_summary_endpoint(web_server: MukhaWebServer) -> None:
    """Verify GET /api/runs/<run_id>/summary returns a terminal run summary."""
    from sarathi.mukha.state import RunSummaryView

    status_404, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/run-fake/summary")
    assert status_404 == 404

    mock_summary = RunSummaryView(
        run_id="run-summary-test-123",
        status="SUCCESS",
        wall_time_ns=500_000_000,
        total_inputs=2,
        successful_files=2,
        warning_files=0,
        failed_files=0,
    )
    with patch.object(web_server, "get_run_summary", return_value=mock_summary):
        status_ok, data_ok, _ = _http_get(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{mock_summary.run_id}/summary"
        )

    assert status_ok == 200
    res = json.loads(data_ok.decode("utf-8"))
    assert res["ok"] is True
    assert res["summary"]["run_id"] == mock_summary.run_id
    assert res["summary"]["status"] == "SUCCESS"
    assert res["summary"]["total_inputs"] == 2


def test_preview_pdf_endpoints(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """Verify PDF preview, multi-page rendering, and raw streaming endpoints."""
    import pymupdf

    pdf_file = tmp_path / "test_doc.pdf"
    doc = pymupdf.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Hello PDF Page 1", fontsize=14)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Hello PDF Page 2", fontsize=14)
    doc.save(str(pdf_file))
    doc.close()

    # 1. Structured preview
    status, data, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path={urllib.parse.quote(str(pdf_file))}"
    )
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    assert res["type"] == "pdf"
    assert res["page_count"] == 2
    assert res["current_page"] == 1
    assert "data:image/png;base64," in res["page_data_url"]
    assert "Hello PDF Page 1" in res["page_text"]

    # 2. Fetch Page 2
    status_p2, data_p2, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview/pdf_page?path={urllib.parse.quote(str(pdf_file))}&page=2"
    )
    assert status_p2 == 200
    res_p2 = json.loads(data_p2.decode("utf-8"))
    assert res_p2["ok"] is True
    assert res_p2["page_number"] == 2
    assert "Hello PDF Page 2" in res_p2["page_text"]

    # 3. Raw PDF stream
    status_raw, bytes_raw, headers_raw = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview/raw?path={urllib.parse.quote(str(pdf_file))}"
    )
    assert status_raw == 200
    assert "application/pdf" in headers_raw.get("Content-Type", "")
    assert "inline" in headers_raw.get("Content-Disposition", "")
    assert len(bytes_raw) == pdf_file.stat().st_size


def test_preview_docx_endpoints(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """Verify Word (.docx) document structured preview and raw streaming."""
    from sarathi.sankalpa import CanonicalDocument
    from sarathi.shakti.docx_exporter import build_docx_payload

    docx_file = tmp_path / "sample_word.docx"
    doc_in = CanonicalDocument(
        document_id="doc-w1",
        source_input_id="inp-1",
        text="Executive Summary Paragraph.\nSecond Body Paragraph with facts.",
    )
    payload = build_docx_payload(doc_in, "sample_word.docx")
    docx_file.write_bytes(payload.content)

    # 1. Structured preview
    status, data, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path={urllib.parse.quote(str(docx_file))}"
    )
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    assert res["type"] == "word"
    assert res["total_paragraphs"] >= 2
    assert any("Executive Summary" in p for p in res["paragraphs"])

    # 2. Raw stream
    status_raw, bytes_raw, headers_raw = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview/raw?path={urllib.parse.quote(str(docx_file))}"
    )
    assert status_raw == 200
    assert "wordprocessingml" in headers_raw.get("Content-Type", "")
    assert len(bytes_raw) == docx_file.stat().st_size


def test_preview_txt_endpoints(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """Verify text file preview with multi-encoding support."""
    txt_file = tmp_path / "sample_text.txt"
    txt_file.write_text("Line 1: System Operational\nLine 2: Ready for production", encoding="utf-8")

    status, data, _ = _http_get(
        f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path={urllib.parse.quote(str(txt_file))}"
    )
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    assert res["type"] == "text"
    assert "System Operational" in res["content"]


def test_preview_failure_boundary_does_not_leak_raw_exceptions(web_server: MukhaWebServer, tmp_path: Path) -> None:
    """Verify preview failures return sanitized errors without leaking internal traceback or raw exceptions."""
    from unittest.mock import patch

    txt_file = tmp_path / "corrupt.txt"
    txt_file.write_text("dummy", encoding="utf-8")

    with patch("builtins.open", side_effect=PermissionError("Internal /secret/disk/denied")):
        status, data, _ = _http_get(
            f"http://127.0.0.1:{web_server.resolved_port}/api/preview?path={urllib.parse.quote(str(txt_file))}"
        )
        assert status == 500
        res = json.loads(data.decode("utf-8"))
        assert res["ok"] is False
        assert res["error"] == "Failed to read document preview."
        assert "/secret/disk/denied" not in res["error"]
        assert "PermissionError" not in res["error"]


def test_persisted_run_summary_reopening_across_restarts(web_server: MukhaWebServer) -> None:
    """Historical run summary must be reconstructed from Darpana when runner has no in-memory summary."""
    from sarathi.darpana.history import TerminalRunSummary

    run_id = "run_hist123456"
    term = TerminalRunSummary(
        run_id=run_id,
        request_id=run_id,
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-08T10:00:00.000000Z",
        completed_at_utc="2026-09-08T10:00:05.000000Z",
        duration_ms=5000,
        artifact_count=3,
        warning_count=1,
    )
    web_server.agni.darpana.record_run_summary(term)

    # In-memory runner summary is cleared (simulating fresh server restart)
    web_server.runner.clear_history()

    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/summary")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    summary = res["summary"]
    assert summary["run_id"] == run_id
    assert summary["status"] == "WARNING"
    assert summary["wall_time_ns"] == 5_000_000_000
    assert summary["total_inputs"] >= 1
    assert summary["warning_files"] == 1


def test_history_query_canonical_schema(web_server: MukhaWebServer) -> None:
    """GET /api/history must supply status, total_inputs, and wall_time_ns required by history drawer."""
    from sarathi.darpana.history import TerminalRunSummary

    run_id = "run_histschema1"
    term = TerminalRunSummary(
        run_id=run_id,
        request_id=run_id,
        requirement="ocr",
        profile="accurate",
        status="completed",
        start_time_utc="2026-09-08T11:00:00.000000Z",
        completed_at_utc="2026-09-08T11:00:02.000000Z",
        duration_ms=2000,
        artifact_count=4,
        warning_count=0,
    )
    web_server.agni.darpana.record_run_summary(term)

    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/history?limit=10")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    items = [h for h in res["history"] if h["run_id"] == run_id]
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "SUCCESS"
    assert item["total_inputs"] == 4
    assert item["wall_time_ns"] == 2_000_000_000
    assert item["duration_ms"] == 2000


def test_consistent_json_error_for_unknown_api_endpoints(web_server: MukhaWebServer) -> None:
    """Unmatched /api/* routes must return structured JSON errors rather than HTML error pages."""
    status, data, headers = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/nonexistent_resource")
    assert status == 404
    assert "application/json" in headers.get("Content-Type", "")
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is False
    assert "error" in res


def test_failed_historical_summary_failures_is_sequence(web_server: MukhaWebServer) -> None:
    """Item 16 (E03): Failed historical summary must return failures as a list of strings for UI .map()."""
    from sarathi.darpana.history import TerminalRunSummary

    run_id = "run_failseq1"
    term = TerminalRunSummary(
        run_id=run_id,
        request_id=run_id,
        requirement="ocr",
        profile="accurate",
        status="failed",
        start_time_utc="2026-09-08T11:00:00.000000Z",
        completed_at_utc="2026-09-08T11:00:01.000000Z",
        duration_ms=1000,
        artifact_count=0,
        warning_count=0,
    )
    web_server.agni.darpana.record_run_summary(term)

    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/summary")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    summary = res["summary"]
    assert summary["status"] == "FAILED"
    assert isinstance(summary["failures"], list)
    assert len(summary["failures"]) == 1
    assert summary["failures"][0] == "Execution failed."


def test_inspector_historical_run_does_not_borrow_active_status(web_server: MukhaWebServer) -> None:
    """Item 21 (E08): Viewing inspector for inactive run uses its own terminal status and duration."""
    from sarathi.darpana.history import TerminalRunSummary

    run_a = "run_hist_a_ok"
    term_a = TerminalRunSummary(
        run_id=run_a,
        request_id=run_a,
        requirement="ocr",
        profile="accurate",
        status="completed",
        start_time_utc="2026-09-08T11:00:00.000000Z",
        completed_at_utc="2026-09-08T11:00:03.000000Z",
        duration_ms=3000,
        artifact_count=1,
        warning_count=0,
    )
    web_server.agni.darpana.record_run_summary(term_a)

    # Set runner's active snapshot to a cancelled terminal run
    with web_server._runner._lock:
        web_server._runner._active_run_id = "run_b_cancelled"
        web_server._runner._terminal_status = "CANCELLED"

    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_a}/inspector")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    inspector = res["inspector"]
    assert inspector["status"] == "SUCCESS"
    assert inspector["elapsed_ns"] == 3_000_000_000


def test_state_builder_derives_policy_label(web_server: MukhaWebServer) -> None:
    """Item 25 (E12): ApplicationViewState derives policy_label dynamically from Kavacha."""
    from sarathi.kavacha.policy import SecurityPolicy
    from sarathi.kavacha.service import Kavacha

    # Default is local only
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["state"]["policy_label"] == "Local only"

    # When external processing is allowed, policy_label reports Cloud enabled
    web_server.agni._kavacha = Kavacha(
        SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=True,
            allow_external_processing=True,
            allowed_secrets=(),
        )
    )
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["state"]["policy_label"] == "Cloud enabled"


def test_concurrent_intake_does_not_block_server_lock(tmp_path: Path) -> None:
    """Intake discovery must run outside server lock to prevent blocking concurrent status queries."""
    import threading
    from unittest.mock import MagicMock

    from sarathi.sankalpa import ExecutionProfile

    mock_agni = MagicMock()
    mock_agni.output_root = tmp_path / "output"
    mock_agni.runtime_root = tmp_path / "runtime"
    mock_agni.kavacha = None
    mock_agni.kosh.capabilities.return_value = ()

    server = MukhaWebServer(mock_agni, host="127.0.0.1", port=0)

    # Mock intake_from_paths with a controlled delay
    def delayed_intake(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.1)
        return (), MagicMock(items=()), MagicMock(eligible_count=0)

    t1_started = threading.Event()
    lock_acquisition_time: float = -1.0

    def run_intake() -> None:
        t1_started.set()
        server.start_run(
            paths=[tmp_path],
            requirement="read_native",
            profile=ExecutionProfile.INSTANT,
        )

    with patch("sarathi.mukha.presenter.MukhaPresenter.intake_from_paths", side_effect=delayed_intake):
        t1 = threading.Thread(target=run_intake)
        t1.start()

        t1_started.wait()
        time.sleep(0.02)  # ensure t1 is inside delayed_intake

        # Thread 2 attempts to query server status while t1 is inside intake
        t2_start = time.perf_counter()
        is_busy = server.is_busy()
        lock_acquisition_time = time.perf_counter() - t2_start

        t1.join()

    # Thread 2 must acquire the lock immediately (< 30ms), not blocked for 100ms by intake
    assert is_busy is False
    assert lock_acquisition_time < 0.05, f"Lock acquisition took {lock_acquisition_time:.4f}s; intake held the lock!"


def test_inspector_endpoint_returns_200_for_run(web_server: MukhaWebServer, tmp_path: Path) -> None:
    from sarathi.sankalpa import Result

    f1 = tmp_path / "doc.txt"
    f1.write_text("Hello Inspector", encoding="utf-8")

    with patch.object(web_server._agni, "execute", return_value=Result(data=None)):
        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={"paths": [str(f1)], "requirement": "read_native"},
        )
        assert status == 200
        run_id = data["run_id"]
        _wait_for_idle(web_server)

        status, body, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/inspector")
        assert status == 200
        insp_data = json.loads(body.decode("utf-8"))
        assert insp_data["ok"] is True
        inspector = insp_data["inspector"]
        assert inspector["run_id"] == run_id
        assert "activity_logs" in inspector
        assert "device_summaries" in inspector
        assert "stage_timings" in inspector
        assert "system_facts" in inspector


def test_inspector_endpoint_rejects_invalid_id(web_server: MukhaWebServer) -> None:
    status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/bad..id/inspector")
    assert status == 400


def test_inspector_endpoint_404_for_unknown_run(web_server: MukhaWebServer) -> None:
    status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/runs/run_nonexistent_999/inspector")
    assert status == 404


def test_preview_execution_plan_no_inputs() -> None:
    from unittest.mock import MagicMock

    from sarathi.mukha.web.planner import preview_execution_plan

    mock_agni = MagicMock()
    mock_agni.kavacha = MagicMock()
    mock_agni.runtime_root = Path(".runtime")
    mock_agni.output_root = Path(".output")

    res = preview_execution_plan(
        agni=mock_agni,
        paths=[],
        requirement="read_native",
    )
    assert res["ok"] is False
    assert "No eligible input documents" in res["error"]


def test_preview_execution_plan_mock_success(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from sarathi.mukha.web.planner import preview_execution_plan
    from sarathi.sankalpa import DeviceType, ExecutionProfile
    from sarathi.yantra.devices import DeviceInfo

    test_file = tmp_path / "test.txt"
    test_file.write_text("sample content", encoding="utf-8")

    mock_agni = MagicMock()
    mock_agni.kavacha.validate_read_path.return_value = test_file
    mock_agni.kavacha.policy.is_path_allowed.return_value = True
    mock_agni.runtime_root = tmp_path / "runtime"
    mock_agni.output_root = tmp_path / "output"

    mock_plan = MagicMock()
    mock_plan.capability_ids = ("read_native",)
    mock_agni.manthan.resolve.return_value = mock_plan

    mock_cap = MagicMock()
    mock_cap.name = "Native Text Extraction"
    mock_agni.kosh.get_capability.return_value = mock_cap

    concrete_device = DeviceInfo(device_id="cpu:0", device_type=DeviceType.CPU, capacity=4)
    mock_agni.yantra.inventory.devices = [concrete_device]

    res = preview_execution_plan(
        agni=mock_agni,
        paths=[test_file],
        requirement="read_native",
        profile=ExecutionProfile.INSTANT,
    )
    assert res["ok"] is True
    assert res["document_count"] == 1
    assert "read_native" in res["capabilities"]
    assert len(res["stages"]) >= 4
    assert any("Native Text Extraction" in s["name"] for s in res["stages"])
    assert len(res["devices"]) == 1


def test_state_endpoint_includes_version_and_revision(web_server: MukhaWebServer) -> None:
    status, data, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
    assert status == 200
    res = json.loads(data.decode("utf-8"))
    assert res["ok"] is True
    assert res["schema_version"] == 1
    assert isinstance(res["state_revision"], int)
    assert res["state_revision"] >= 1
    assert res["state"]["schema_version"] == 1
    assert res["state"]["state_revision"] == res["state_revision"]


def test_state_revision_monotonic_increment(web_server: MukhaWebServer) -> None:
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

    status_post, res_post = _http_post(
        f"http://127.0.0.1:{web_server.resolved_port}/api/review",
        {"item_id": "rev-1", "attempt_id": "att-ver-1", "action_id": "accept"},
    )
    assert status_post == 200
    assert res_post["ok"] is True
    assert web_server.runner.state_revision > r0


def test_sse_emits_schema_version_and_state_revision(web_server: MukhaWebServer) -> None:
    url = f"http://127.0.0.1:{web_server.resolved_port}/api/events"
    req = urllib.request.Request(
        url,
        headers={"Host": "127.0.0.1", "Cookie": f"sarathi_session={web_server.auth_token}"},
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
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
    assert payload["state_revision"] >= 1


def test_ui_endpoint_rejects_traversal(web_server: MukhaWebServer) -> None:
    status, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/..%2F..%2Fsecret.py")
    assert status == 404
    status_missing, _, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/nonexistent.js")
    assert status_missing == 404


def test_preview_dialog_and_close_button_contract(web_server: MukhaWebServer) -> None:
    status_app, data_app, _ = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/ui/app.js")
    assert status_app == 200
    app_js = data_app.decode("utf-8")
    assert "doc-preview-dialog" in app_js
    assert "btn-close-preview" in app_js
    assert "command-palette-dialog" in app_js
    assert "palette-search-input" in app_js


def test_action_parameter_view_serialization() -> None:
    from sarathi.mukha.state import ActionParameterView
    from sarathi.mukha.web.security import _serialize_dataclass

    param = ActionParameterView(
        parameter_id="profile",
        display_name="OCR Execution Profile",
        kind="select",
        default_value="instant",
        options=(("instant", "Instant"), ("accurate", "Accurate")),
        is_required=True,
    )
    data = _serialize_dataclass(param)
    assert data["parameter_id"] == "profile"
    assert data["kind"] == "select"
    assert data["default_value"] == "instant"
    assert len(data["options"]) == 2


def test_build_action_parameters_ocr_and_font() -> None:
    from sarathi.mukha.web.state_builder import _build_action_parameters

    ocr_params = _build_action_parameters("ocr")
    assert any(p.parameter_id == "profile" for p in ocr_params)
    assert any(p.parameter_id == "lang" for p in ocr_params)

    font_params = _build_action_parameters("font_conversion")
    assert any(p.parameter_id == "source_font" for p in font_params)
    assert any(p.parameter_id == "font_mode" for p in font_params)
    assert _build_action_parameters("unknown_action") == ()


def test_diagnostics_export_sanitization() -> None:
    from unittest.mock import MagicMock

    from sarathi.darpana import MarutiRecord, PramanaRecord
    from sarathi.mukha.web.diagnostics import export_run_diagnostics
    from sarathi.sankalpa import ConfidenceValue

    mock_agni = MagicMock()
    mock_agni.darpana.maruti_records.return_value = (
        MarutiRecord(
            run_id="run-diag",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            phase_name="optical_character_recognition",
            component="rapidocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            duration_ns=150_000_000,
            outcome="success",
            attributes={"text": "SECRET", "page": 1, "chars": 120},
        ),
    )
    mock_agni.darpana.pramana_records.return_value = (
        PramanaRecord(
            run_id="run-diag",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-page",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            confidence=ConfidenceValue(score=0.96, method="test", evidence={"samples": 10}),
            attributes={"level": "page"},
        ),
    )
    diag = export_run_diagnostics(mock_agni, "run-diag", "127.0.0.1", 8765)
    assert diag["schema"] == "sarathi.diagnostics.v1"
    assert diag["run_id"] == "run-diag"
    assert "optical_character_recognition" in diag["stages"]
    assert "text" not in diag["events"][0]["attributes"]


def test_run_comparison_analytics() -> None:
    from unittest.mock import MagicMock

    from sarathi.darpana import MarutiRecord, PramanaRecord
    from sarathi.mukha.web.comparison import compare_runs
    from sarathi.sankalpa import ConfidenceValue

    mock_agni = MagicMock()
    mock_agni.darpana.maruti_records.return_value = (
        MarutiRecord(
            run_id="run-a",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            phase_name="ocr",
            component="rapidocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            duration_ns=100_000_000,
            outcome="success",
        ),
        MarutiRecord(
            run_id="run-b",
            request_id="req-2",
            trace_id="tr-2",
            span_id="sp-2",
            phase_name="ocr",
            component="rapidocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            duration_ns=75_000_000,
            outcome="success",
        ),
    )
    mock_agni.darpana.pramana_records.return_value = (
        PramanaRecord(
            run_id="run-a",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-a",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            confidence=ConfidenceValue(score=0.85, method="test", evidence={"samples": 10}),
            attributes={"level": "page"},
        ),
        PramanaRecord(
            run_id="run-b",
            request_id="req-2",
            trace_id="tr-2",
            span_id="sp-b",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            confidence=ConfidenceValue(score=0.95, method="test", evidence={"samples": 10}),
            attributes={"level": "page"},
        ),
    )
    res = compare_runs(mock_agni, "run-a", "run-b")
    assert res["ok"] is True
    assert res["summary"]["duration_ms_a"] == 100.0
    assert res["summary"]["duration_ms_b"] == 75.0
    assert res["summary"]["confidence_diff"] == 0.1
