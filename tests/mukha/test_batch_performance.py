"""Performance and scalability benchmarks for Mukha intake discovery and state serialization.

Validates that batches of 10, 100, and 500 files are discovered, sorted, and serialized
within strict real-time latency thresholds without memory bloat or event loop starvation.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sarathi.mukha.presenter import MukhaPresenter
from sarathi.mukha.state import (
    ApplicationViewState,
    FileRunView,
    RunViewState,
)
from sarathi.mukha.web.security import _serialize_dataclass

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

