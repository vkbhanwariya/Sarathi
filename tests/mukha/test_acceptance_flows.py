"""Comprehensive end-to-end acceptance tests for Mukha presentation workflows."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.mukha.web.comparison import compare_runs
from sarathi.mukha.web.diagnostics import export_run_diagnostics
from sarathi.mukha.web.server import MukhaWebServer
from sarathi.sankalpa import ConfidenceValue


def test_diagnostics_export_sanitization() -> None:
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
            attributes={"text": "SECRET TEXT THAT SHOULD BE STRIPPED", "page": 1, "chars": 120},
        ),
    )
    mock_agni.darpana.pramana_records.return_value = (
        PramanaRecord(
            run_id="run-diag",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            confidence=ConfidenceValue(score=0.96, method="test", evidence={"samples": 10}),
        ),
    )

    diag = export_run_diagnostics(mock_agni, "run-diag", "127.0.0.1", 8765)
    assert diag["schema"] == "sarathi.diagnostics.v1"
    assert diag["run_id"] == "run-diag"
    assert diag["system"]["security_policy"] == "Kavacha Local Isolation"
    assert "optical_character_recognition" in diag["stages"]
    assert diag["confidence_statistics"]["avg_confidence"] == 0.96

    # Verify sensitive attributes are stripped
    event = diag["events"][0]
    assert "text" not in event["attributes"]
    assert event["attributes"]["page"] == "1"


def test_run_comparison_analytics() -> None:
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
            span_id="sp-1",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            confidence=ConfidenceValue(score=0.85, method="test", evidence={"samples": 10}),
        ),
        PramanaRecord(
            run_id="run-b",
            request_id="req-2",
            trace_id="tr-2",
            span_id="sp-2",
            capability_id="ocr",
            stage="ocr",
            timestamp_utc="2026-09-07T00:00:00Z",
            confidence=ConfidenceValue(score=0.95, method="test", evidence={"samples": 10}),
        ),
    )

    res = compare_runs(mock_agni, "run-a", "run-b")
    assert res["ok"] is True
    assert res["summary"]["duration_ms_a"] == 100.0
    assert res["summary"]["duration_ms_b"] == 75.0
    assert res["summary"]["duration_diff_ms"] == -25.0
    assert res["summary"]["confidence_diff"] == 0.1
    assert len(res["stages"]) == 1
    assert res["stages"][0]["stage"] == "ocr"
    assert res["stages"][0]["diff_ms"] == -25.0


def test_acceptance_server_api_flows(tmp_path: Path) -> None:
    test_file = tmp_path / "test.txt"
    test_file.write_text("sample content", encoding="utf-8")

    mock_agni = MagicMock()
    mock_agni.kavacha.validate_read_path.return_value = test_file
    mock_agni.kavacha.policy.is_path_allowed.return_value = True
    mock_agni.runtime_root = tmp_path / "runtime"
    mock_agni.output_root = tmp_path / "output"
    mock_agni.kosh.capabilities.return_value = ()
    mock_agni.darpana = None

    server = MukhaWebServer(agni=mock_agni, host="127.0.0.1", port=0)
    server.start()
    try:
        base = server.local_url

        # 1. Verify app.html contains palette dialog
        with urllib.request.urlopen(f"{base}/") as resp:
            html = resp.read().decode("utf-8")
            assert 'id="command-palette-dialog"' in html
            assert 'id="btn-export-diagnostics"' in html

        # 2. Verify palette.js static route
        with urllib.request.urlopen(f"{base}/js/palette.js") as resp:
            assert resp.status == 200
            assert "openCommandPalette" in resp.read().decode("utf-8")

        # 3. Verify diagnostics endpoint
        with urllib.request.urlopen(f"{base}/api/runs/test-run-id/diagnostics") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["schema"] == "sarathi.diagnostics.v1"
            assert data["run_id"] == "test-run-id"

        # 4. Verify compare endpoint
        with urllib.request.urlopen(f"{base}/api/runs/compare?run_a=run-1&run_b=run-2") as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["run_id_a"] == "run-1"
            assert data["run_id_b"] == "run-2"
    finally:
        server.stop()
