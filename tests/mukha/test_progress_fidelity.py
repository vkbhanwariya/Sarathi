"""Targeted tests verifying presentation fidelity, worker timing, and truthful state in Mukha."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sarathi.agni import Agni
from sarathi.mukha.web import MukhaWebServer
from sarathi.sankalpa import ArtifactRef, Result


def _http_get(url: str) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP GET returning JSON."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body)


def _http_post(url: str, data: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP POST returning JSON."""
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8")
        return err.code, json.loads(body)


class TestProgressFidelity:
    """Verify factual per-file tracking, worker timings, and zero false metrics."""

    def test_unstarted_files_pending_and_none_elapsed(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Files that haven't started processing must report PENDING with elapsed_ns=None."""
        f1 = tmp_path / "file1.txt"
        f2 = tmp_path / "file2.txt"
        f3 = tmp_path / "file3.txt"
        f1.write_text("content1", encoding="utf-8")
        f2.write_text("content2", encoding="utf-8")
        f3.write_text("content3", encoding="utf-8")

        started_evt = threading.Event()
        finish_evt = threading.Event()

        def mock_execute(req: Any) -> Any:
            prog_cb = req.custom_options["progress_callback"]
            # File 1 starts
            prog_cb(
                file_display_name="file1.txt",
                page_number=1,
                total_pages=1,
                worker_id="w-1",
                stage="Reading Native",
                device_type=None,
            )
            started_evt.set()
            finish_evt.wait(timeout=3.0)
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1), str(f2), str(f3)], "requirement": "read_native"},
            )
            assert status == 200
            assert started_evt.wait(timeout=2.0)

            # Query presentation state while run is active
            status, body = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            assert status == 200
            files = body["state"]["active_run"]["files"]
            assert len(files) == 3

            # File 1 is active
            assert files[0]["display_name"] == "file1.txt"
            assert files[0]["status"] == "RUNNING"
            assert files[0]["elapsed_ns"] is not None

            # File 2 and File 3 are not started
            assert files[1]["display_name"] == "file2.txt"
            assert files[1]["status"] == "PENDING"
            assert files[1]["elapsed_ns"] is None
            assert files[1]["current_stage"] == "Pending"

            assert files[2]["display_name"] == "file3.txt"
            assert files[2]["status"] == "PENDING"
            assert files[2]["elapsed_ns"] is None
            assert files[2]["current_stage"] == "Pending"

            finish_evt.set()

    def test_worker_timing_split_elapsed_and_idle(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Worker elapsed_ns must preserve start time, while idle_ns tracks update time."""
        f1 = tmp_path / "doc.txt"
        f1.write_text("content", encoding="utf-8")

        started_evt = threading.Event()
        second_update_evt = threading.Event()
        finish_evt = threading.Event()

        def mock_execute(req: Any) -> Any:
            prog_cb = req.custom_options["progress_callback"]
            prog_cb(
                file_display_name="doc.txt",
                page_number=1,
                total_pages=5,
                worker_id="w-1",
                stage="Processing",
            )
            started_evt.set()
            second_update_evt.wait(timeout=2.0)
            time.sleep(0.05)
            prog_cb(
                file_display_name="doc.txt",
                page_number=2,
                total_pages=5,
                worker_id="w-1",
                stage="Processing",
            )
            finish_evt.wait(timeout=3.0)
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert started_evt.wait(timeout=2.0)

            # Initial poll
            _, body1 = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            worker1 = body1["state"]["active_run"]["active_workers"][0]
            elapsed1 = worker1["elapsed_ns"]

            time.sleep(0.05)
            second_update_evt.set()
            time.sleep(0.02)

            # Second poll: elapsed_ns must have grown, not reset to zero
            _, body2 = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            worker2 = body2["state"]["active_run"]["active_workers"][0]
            elapsed2 = worker2["elapsed_ns"]

            assert elapsed2 >= elapsed1
            assert "idle_ns" in worker2

            finish_evt.set()

    def test_no_fake_worker_fabricated_when_no_workers_reporting(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """When no workers have reported progress, active_workers must be empty."""
        f1 = tmp_path / "doc.txt"
        f1.write_text("test", encoding="utf-8")

        started_evt = threading.Event()
        finish_evt = threading.Event()

        def mock_execute(req: Any) -> Any:
            started_evt.set()
            finish_evt.wait(timeout=2.0)
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert started_evt.wait(timeout=2.0)

            _, body = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            workers = body["state"]["active_run"]["active_workers"]
            # Must NOT fabricate fake Worker 1
            assert workers == []

            finish_evt.set()

    def test_no_device_defaulting_to_cpu(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Unknown device types must not be fabricated as CPU."""
        f1 = tmp_path / "doc.txt"
        f1.write_text("test", encoding="utf-8")

        started_evt = threading.Event()
        finish_evt = threading.Event()

        def mock_execute(req: Any) -> Any:
            prog_cb = req.custom_options["progress_callback"]
            prog_cb(
                file_display_name="doc.txt",
                page_number=1,
                total_pages=1,
                worker_id="w-1",
                stage="Extraction",
                device_type=None,  # unknown device
            )
            started_evt.set()
            finish_evt.wait(timeout=2.0)
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert started_evt.wait(timeout=2.0)

            _, body = _http_get(f"http://127.0.0.1:{web_server.resolved_port}/api/state")
            worker = body["state"]["active_run"]["active_workers"][0]
            assert worker["device_type"] != "CPU"

            finish_evt.set()

    def test_real_run_populates_confirmed_artifacts(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Completing a real run must automatically register result.artifacts in _confirmed_artifacts."""
        f1 = tmp_path / "doc.txt"
        f1.write_text("Hello World", encoding="utf-8")

        art_file = web_server.output_root / "output.txt"
        art_file.write_text("Processed output", encoding="utf-8")

        art_ref = ArtifactRef(
            artifact_id="art-real-001",
            path=art_file,
            role="document",
            media_type="text/plain",
            size_bytes=len("Processed output"),
            checksum_sha256="abc123",
        )

        def mock_execute(req: Any) -> Any:
            return Result(data=None, artifacts=(art_ref,))

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            status, data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert status == 200
            run_id = data["run_id"]
            time.sleep(0.5)

            # Artifact must be accessible via get_confirmed_artifact
            resolved_ref = web_server.get_confirmed_artifact(run_id, "art-real-001")
            assert resolved_ref is not None
            assert resolved_ref.artifact_id == "art-real-001"

    def test_cancel_run_returns_false_for_finished_run(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """cancel_run must return False when the run is already finished."""
        f1 = tmp_path / "doc.txt"
        f1.write_text("test", encoding="utf-8")

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

            # Try to cancel the finished run
            status, cancel_data = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs/{run_id}/cancel",
                data={},
            )
            assert status == 200
            assert cancel_data["cancelled"] is False

    def test_start_run_409_busy_vs_400_invalid_inputs(
        self, web_server: MukhaWebServer, tmp_path: Path
    ) -> None:
        """Server returns 409 Conflict when busy and 400 Bad Request when inputs are invalid."""
        # 1. Invalid / empty inputs -> 400 Bad Request
        status, data = _http_post(
            f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
            data={"paths": [str(tmp_path / "non_existent_file.xyz")], "requirement": "read_native"},
        )
        assert status == 400
        assert data["ok"] is False

        # 2. Busy server -> 409 Conflict
        f1 = tmp_path / "valid.txt"
        f1.write_text("content", encoding="utf-8")

        started_evt = threading.Event()
        finish_evt = threading.Event()

        def mock_execute(req: Any) -> Any:
            started_evt.set()
            finish_evt.wait(timeout=2.0)
            return Result(data=None)

        with patch.object(web_server._agni, "execute", side_effect=mock_execute):
            status1, _ = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert status1 == 200
            assert started_evt.wait(timeout=2.0)

            # Concurrent start attempt
            status2, data2 = _http_post(
                f"http://127.0.0.1:{web_server.resolved_port}/api/runs",
                data={"paths": [str(f1)], "requirement": "read_native"},
            )
            assert status2 == 409
            assert data2["ok"] is False
            assert "already active" in data2["error"].lower()

            finish_evt.set()
