"""Tests for Mukha execution plan previewer and endpoint."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from sarathi.mukha.web.planner import preview_execution_plan
from sarathi.mukha.web.server import MukhaWebServer
from sarathi.sankalpa import ExecutionProfile


def test_preview_execution_plan_no_inputs() -> None:
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

    mock_device = MagicMock()
    mock_device.device_type = "cpu"
    mock_device.device_id = "cpu:0"
    mock_device.is_available = True
    mock_device.is_preferred = True
    mock_agni.yantra.device_inventory.devices = [mock_device]

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
    stage_names = [s["name"] for s in res["stages"]]
    assert any("Native Text Extraction" in s for s in stage_names)
    assert len(res["devices"]) == 1
    assert res["devices"][0]["device_type"] == "cpu"


def test_post_plan_preview_endpoint(tmp_path: Path) -> None:
    test_file = tmp_path / "doc.txt"
    test_file.write_text("document text", encoding="utf-8")

    mock_agni = MagicMock()
    mock_agni.kavacha.validate_read_path.return_value = test_file
    mock_agni.kavacha.policy.is_path_allowed.return_value = True
    mock_agni.runtime_root = tmp_path / "runtime"
    mock_agni.output_root = tmp_path / "output"
    mock_agni.kosh.capabilities.return_value = ()
    mock_agni.darpana = None

    mock_plan = MagicMock()
    mock_plan.capability_ids = ("read_native",)
    mock_agni.manthan.resolve.return_value = mock_plan

    server = MukhaWebServer(agni=mock_agni, host="127.0.0.1", port=0)
    server.start()
    try:
        url = f"{server.local_url}/api/plan/preview"
        payload = {
            "paths": [str(test_file)],
            "requirement": "read_native",
            "profile": "instant",
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Host": "127.0.0.1"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["document_count"] == 1
            assert "stages" in data
    finally:
        server.stop()
