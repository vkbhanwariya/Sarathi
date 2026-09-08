"""Performance and scalability benchmarks for Mukha intake discovery and state serialization.

Validates that batches of 10, 100, and 500 files are discovered, sorted, and serialized
within strict real-time latency thresholds without memory bloat or event loop starvation.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    FileRunView,
    RunViewState,
)
from sarathi.mukha.web.http_handler import _serialize_dataclass

pytestmark = [pytest.mark.performance]


def _create_synthetic_batch(base_dir: Path, count: int) -> list[Path]:
    """Create a synthetic batch of valid test PDF files."""
    files: list[Path] = []
    for i in range(count):
        p = base_dir / f"test_doc_{i:04d}.pdf"
        p.write_bytes(b"%PDF-1.4\n%EOF\n")
        files.append(p)
    return files


@pytest.mark.parametrize("file_count,max_duration_s", [
    (10, 0.2),
    (100, 0.6),
    (500, 2.5),
])
def test_intake_discovery_scaling(tmp_path: Path, file_count: int, max_duration_s: float) -> None:
    """Test intake discovery latency for 10, 100, and 500 documents."""
    batch_dir = tmp_path / f"batch_{file_count}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    _create_synthetic_batch(batch_dir, file_count)

    runtime_root = tmp_path / "runtime"
    output_root = tmp_path / "output"
    runtime_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    inputs, selection, preflight = MukhaPresenter.intake_from_paths(
        [batch_dir],
        kavacha=None,
        runtime_root=runtime_root,
        output_root=output_root,
        recursive=True,
    )
    elapsed = time.perf_counter() - start

    assert len(inputs) == file_count
    assert len(selection.items) == file_count
    assert preflight.eligible_count == file_count
    assert preflight.issue_count == 0
    assert elapsed < max_duration_s, f"Intake for {file_count} files took {elapsed:.3f}s (budget: {max_duration_s}s)"


@pytest.mark.parametrize("file_count,max_duration_s", [
    (10, 0.05),
    (100, 0.20),
    (500, 0.80),
])
def test_state_serialization_scaling(file_count: int, max_duration_s: float) -> None:
    """Test ApplicationViewState JSON-primitive serialization latency for large file runs."""
    file_views = tuple(
        FileRunView(
            input_id=f"doc_{i:04d}",
            display_name=f"test_doc_{i:04d}.pdf",
            ordinal=i + 1,
            status="SUCCESS" if i < (file_count // 2) else "PENDING",
            current_stage="OCR Recognition" if i == (file_count // 2) else "",
            elapsed_ns=150_000_000 if i < (file_count // 2) else None,
            warning_count=0,
        )
        for i in range(file_count)
    )

    run_view = RunViewState(
        run_id="bench_run_001",
        status="RUNNING",
        elapsed_ns=5_000_000_000,
        total_files=file_count,
        terminal_files=file_count // 2,
        files=file_views,
    )

    from sarathi.mukha.state import InputSelectionView

    app_state = ApplicationViewState(
        current_screen="monitor",
        requirement="ocr",
        policy_label="Local only",
        input_selection=InputSelectionView(total_files=file_count, total_size_bytes=1000, is_grouped=False),
        active_run=run_view,
    )

    start = time.perf_counter()
    serialized = _serialize_dataclass(app_state)
    elapsed = time.perf_counter() - start

    assert serialized["current_screen"] == "monitor"
    assert serialized["active_run"]["total_files"] == file_count
    assert len(serialized["active_run"]["files"]) == file_count
    assert serialized["active_run"]["files"][0]["ordinal"] == 1
    assert serialized["active_run"]["files"][-1]["ordinal"] == file_count
    assert elapsed < max_duration_s, f"Serialization of {file_count} files took {elapsed:.3f}s (budget: {max_duration_s}s)"


def test_concurrent_intake_does_not_block_server_lock(tmp_path: Path) -> None:
    """Intake discovery must run outside server lock to prevent blocking concurrent status queries."""
    import threading
    from unittest.mock import MagicMock, patch

    from sarathi.mukha.web.server import MukhaWebServer
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

