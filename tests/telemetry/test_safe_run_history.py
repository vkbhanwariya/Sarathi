"""Tests for Retained Safe Run History, Privacy Guarantees, Reopening, and Storage Isolation."""

import json
from pathlib import Path

import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana, TerminalRunHistoryStore, TerminalRunSummary
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    InputRef,
    Request,
)
from sarathi.sutra import Settings


def test_terminal_run_summary_validation() -> None:
    """Test strict validation of TerminalRunSummary dataclass fields."""
    summary = TerminalRunSummary(
        run_id="run-1",
        request_id="req-1",
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:01Z",
        duration_ms=1000,
        artifact_count=1,
        warning_count=0,
    )
    assert summary.run_id == "run-1"
    assert summary.to_dict()["status"] == "completed"

    # Test invalid status
    with pytest.raises(ValueError):
        TerminalRunSummary(
            run_id="run-1",
            request_id="req-1",
            requirement="read_native",
            profile="instant",
            status="unknown_status",
            start_time_utc="2026-09-02T12:00:00Z",
            completed_at_utc="2026-09-02T12:00:01Z",
            duration_ms=100,
            artifact_count=0,
            warning_count=0,
        )


def test_history_jsonl_persistence_and_reopen(tmp_path: Path) -> None:
    """Test saving and reopening terminal run summaries via JSONL history store."""
    history_file = tmp_path / "telemetry" / "runs.jsonl"
    darpana1 = Darpana(capacity=100, history_path=history_file, history_format="jsonl")

    sum1 = TerminalRunSummary(
        run_id="run-1",
        request_id="req-1",
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:01Z",
        duration_ms=1000,
        artifact_count=2,
        warning_count=0,
    )
    sum2 = TerminalRunSummary(
        run_id="run-2",
        request_id="req-2",
        requirement="ocr",
        profile="accurate",
        status="cancelled",
        start_time_utc="2026-09-02T12:01:00Z",
        completed_at_utc="2026-09-02T12:01:02Z",
        duration_ms=2000,
        artifact_count=0,
        warning_count=1,
    )

    darpana1.record_run_summary(sum1)
    darpana1.record_run_summary(sum2)

    assert history_file.exists()

    # Reopen across new Darpana instance (simulating application restart)
    darpana2 = Darpana(capacity=100, history_path=history_file, history_format="jsonl")
    history = darpana2.query_run_history(limit=10)

    assert len(history) == 2
    # Newest run first
    assert history[0].run_id == "run-2"
    assert history[0].status == "cancelled"
    assert history[1].run_id == "run-1"
    assert history[1].status == "completed"

    found = darpana2.get_run_summary("run-1")
    assert found is not None
    assert found.requirement == "read_native"


def test_history_sqlite_persistence_and_reopen(tmp_path: Path) -> None:
    """Test saving and reopening terminal run summaries via SQLite history store."""
    history_db = tmp_path / "telemetry" / "runs.db"
    darpana1 = Darpana(capacity=100, history_path=history_db, history_format="sqlite")

    sum1 = TerminalRunSummary(
        run_id="run-sql-1",
        request_id="req-sql-1",
        requirement="bank_statements",
        profile="accurate",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:03Z",
        duration_ms=3000,
        artifact_count=1,
        warning_count=0,
    )
    darpana1.record_run_summary(sum1)

    # Reopen across restart
    darpana2 = Darpana(capacity=100, history_path=history_db, history_format="sqlite")
    history = darpana2.query_run_history(limit=10)

    assert len(history) == 1
    assert history[0].run_id == "run-sql-1"
    assert history[0].requirement == "bank_statements"
    assert history[0].duration_ms == 3000

    found = darpana2.get_run_summary("run-sql-1")
    assert found is not None
    assert found.profile == "accurate"


def test_history_storage_failure_isolation(tmp_path: Path) -> None:
    """Test that persistence errors do not crash recording or processing."""
    # Point history to an invalid path that cannot be written
    invalid_path = tmp_path / "not_a_dir" / "dummy"
    invalid_path.parent.write_text("file blocking directory creation", encoding="utf-8")

    darpana = Darpana(capacity=10, history_path=invalid_path, history_format="jsonl")
    sum1 = TerminalRunSummary(
        run_id="run-isolated",
        request_id="req-isolated",
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:01Z",
        duration_ms=500,
        artifact_count=1,
        warning_count=0,
    )

    # Must not raise exception
    darpana.record_run_summary(sum1)

    # In-memory history still works
    in_memory = darpana.query_run_history()
    assert len(in_memory) == 1
    assert in_memory[0].run_id == "run-isolated"


def test_agni_execution_records_history_via_sutra_settings(tmp_path: Path) -> None:
    """Test end-to-end Agni execution automatically writes run history when enabled in Sutra."""
    settings = Settings(
        data={
            "telemetry": {
                "history_enabled": True,
                "history_path": "custom_history.jsonl",
                "history_format": "jsonl",
            }
        }
    )

    input_file = tmp_path / "test.txt"
    input_file.write_text("hello history world", encoding="utf-8")

    # 1. Successful execution
    with Agni(
        settings=settings,
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
    ) as agni:
        req = Request(
            request_id="req-e2e-hist",
            requirement="read_native",
            inputs=(InputRef("inp-1", input_file, "test.txt", 19),),
        )
        res = agni.execute(req)
        assert res.data is not None

        # Verify history was recorded in Agni's Darpana and in JSONL
        history = agni.darpana.query_run_history(limit=5)
        assert len(history) == 1
        assert history[0].request_id == "req-e2e-hist"
        assert history[0].status == "completed"
        assert history[0].artifact_count >= 0

    resolved_history_file = tmp_path / "Runtime" / "Telemetry" / "custom_history.jsonl"
    reopened_darpana = Darpana(capacity=100, history_path=resolved_history_file, history_format="jsonl")
    reopened_history = reopened_darpana.query_run_history(limit=5)
    assert len(reopened_history) == 1
    assert reopened_history[0].request_id == "req-e2e-hist"


def test_agni_failure_sanitizes_request_id_and_preserves_root_exception(tmp_path: Path) -> None:
    """When pipeline fails, request_id is safely sanitized and the root error is not masked."""
    from sarathi.dosh import DoshError

    settings = Settings(
        data={
            "telemetry": {
                "history_enabled": True,
                "history_path": "failure_history.jsonl",
                "history_format": "jsonl",
            }
        }
    )

    with Agni(
        settings=settings,
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
    ) as agni:
        doc_file = tmp_path / "doc.txt"
        doc_file.write_text("sample content", encoding="utf-8")

        # Request with requirement that fails Manthan resolution
        req = Request(
            request_id="req-failing-test",
            requirement="nonexistent_capability",
            inputs=(InputRef("inp-1", doc_file, "doc.txt", 14),),
        )
        with pytest.raises(DoshError) as exc_info:
            agni.execute(req)

        # Root error is preserved
        assert "No capability registered" in exc_info.value.message

        # Failure summary was safely recorded
        history = agni.darpana.query_run_history(limit=5)
        assert len(history) == 1
        assert history[0].status == "failed"
        assert history[0].request_id == "req-failing-test"


def test_darpana_clear_history_jsonl_and_sqlite(tmp_path: Path) -> None:
    """Test clearing terminal run history across both JSONL and SQLite persistent stores."""
    # 1. JSONL store
    jsonl_path = tmp_path / "telemetry" / "runs.jsonl"
    darpana_jsonl = Darpana(capacity=10, history_path=jsonl_path, history_format="jsonl")
    sum1 = TerminalRunSummary(
        run_id="run-j1",
        request_id="req-j1",
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:01Z",
        duration_ms=1000,
        artifact_count=1,
        warning_count=0,
    )
    darpana_jsonl.record_run_summary(sum1)
    assert len(darpana_jsonl.query_run_history()) == 1
    assert darpana_jsonl.clear_history() is True
    assert len(darpana_jsonl.query_run_history()) == 0

    # 2. SQLite store
    sqlite_path = tmp_path / "telemetry" / "runs.db"
    darpana_sqlite = Darpana(capacity=10, history_path=sqlite_path, history_format="sqlite")
    sum2 = TerminalRunSummary(
        run_id="run-s1",
        request_id="req-s1",
        requirement="ocr",
        profile="accurate",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:02Z",
        duration_ms=2000,
        artifact_count=1,
        warning_count=0,
    )
    darpana_sqlite.record_run_summary(sum2)
    assert len(darpana_sqlite.query_run_history()) == 1
    assert darpana_sqlite.clear_history() is True
    assert len(darpana_sqlite.query_run_history()) == 0


def test_history_path_rejects_absolute_and_traversal_paths(tmp_path: Path) -> None:
    """Proves Agni rejects absolute telemetry.history_path and traversal escaping Runtime/Telemetry."""
    rt_dir = tmp_path / "Runtime"
    out_dir = tmp_path / "Output"

    # Case 1: Absolute path rejected
    abs_settings = Settings(
        data={
            "telemetry": {
                "history_enabled": True,
                "history_path": (tmp_path / "abs_history.jsonl").as_posix(),
            }
        }
    )
    with pytest.raises(DoshError) as exc_info:
        Agni(settings=abs_settings, runtime_root=rt_dir, output_root=out_dir)
    assert exc_info.value.code is FailureCode.INVALID_CONFIGURATION
    assert "absolute path" in exc_info.value.message

    # Case 2: Traversal escaping Runtime/Telemetry rejected
    traversal_settings = Settings(
        data={
            "telemetry": {
                "history_enabled": True,
                "history_path": "../escaped_history.jsonl",
            }
        }
    )
    with pytest.raises(DoshError) as exc_info2:
        Agni(settings=traversal_settings, runtime_root=rt_dir, output_root=out_dir)
    assert exc_info2.value.code is FailureCode.INVALID_CONFIGURATION
    assert "escapes" in exc_info2.value.message


def test_jsonl_history_bounded_tail_with_oversized_existing_file(tmp_path: Path) -> None:
    """Proves JSONL save and query handle oversized pre-existing files without unbounded accumulation."""
    jsonl_path = tmp_path / "oversized_history.jsonl"

    seed_lines = []
    for i in range(50):
        entry = {
            "run_id": f"run-old-{i:03d}",
            "request_id": f"req-old-{i:03d}",
            "requirement": "read_native",
            "profile": "instant",
            "status": "completed",
            "start_time_utc": "2026-09-02T12:00:00Z",
            "completed_at_utc": f"2026-09-02T12:00:{i:02d}Z",
            "duration_ms": 100,
            "artifact_count": 0,
            "warning_count": 0,
            "has_masked_identity": False,
        }
        seed_lines.append(json.dumps(entry))
    jsonl_path.write_text("\n".join(seed_lines) + "\n", encoding="utf-8")

    store = TerminalRunHistoryStore(jsonl_path, format="jsonl", max_records=5)

    new_summary = TerminalRunSummary(
        run_id="run-new-001",
        request_id="req-new-001",
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:01:00Z",
        duration_ms=100,
        artifact_count=0,
        warning_count=0,
    )
    assert store.save(new_summary) is True

    remaining_lines = [ln.strip() for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(remaining_lines) == 5
    assert "run-new-001" in remaining_lines[-1]

    queried = store.query(limit=3)
    assert len(queried) == 3
    assert queried[0].run_id == "run-new-001"
