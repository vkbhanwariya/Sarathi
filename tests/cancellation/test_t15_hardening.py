"""Focused Adversarial Tests for T15: Runtime Intake, Cancellation, and Safe History.

Verifies:
1. Canonical Mukha intake owner and CLI parity with Sutra-resolved roots;
2. Pure presenter projection without direct filesystem operations;
3. Safe CLI validation output formatting without raw paths;
4. Cancellation token strict type validation and reconciliation at Agni entry;
5. Continuation request token preservation;
6. Cancellation bypasses retry loops, quarantine store, and cache writes;
7. Terminal cancelled outcome produced if cancelled after capability execution;
8. Artifact semantics on failure/cancellation (ordinary committed artifacts removed, partial preserved only under partial/);
9. Safe retained history schema validation, from_dict non-coercion, and bounded retention (SQLite & JSONL);
10. Observable history persistence failure without pipeline disruption.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sarathi.__main__ import main as cli_main
from sarathi.agni import Agni
from sarathi.darpana import Darpana, TerminalRunHistoryStore, TerminalRunSummary
from sarathi.dosh import DoshError, FailureCode
from sarathi.mukha import MukhaPresenter, intake_from_paths
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
)
from sarathi.sutra import Settings


class MockSuccessCapability:
    def __init__(self, next_req: str | None = None) -> None:
        from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

        self.declaration = CAPABILITY_DECLARATION
        self.next_req = next_req
        self.call_count = 0

    def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
        self.call_count += 1
        doc = CanonicalDocument(
            document_id="doc-test-1",
            source_input_id=request.inputs[0].input_id,
            text="SAMPLE PARSED TEXT",
            pages=(PageData(page_number=1, text="SAMPLE PARSED TEXT", tables=()),),
            tables=(),
        )
        return Result(data=doc, next_requirement=self.next_req)


# ---------------------------------------------------------------------------
# 1. Canonical Mukha Intake and CLI Parity with Configured Roots
# ---------------------------------------------------------------------------


def test_intake_from_paths_canonical_and_pure_presenter(tmp_path: Path) -> None:
    """Proves canonical intake handles multiline pasted strings and MukhaPresenter delegates cleanly."""
    f1 = tmp_path / "doc1.txt"
    f2 = tmp_path / "doc2.txt"
    f1.write_text("content 1", encoding="utf-8")
    f2.write_text("content 2", encoding="utf-8")

    pasted = f'"{f1}"\n"{f2}"'
    refs, sel, pf = intake_from_paths([pasted])

    assert len(refs) == 2
    assert pf.eligible_count == 2
    assert pf.issue_count == 0
    assert {r.display_name for r in refs} == {"doc1.txt", "doc2.txt"}

    # MukhaPresenter delegates to intake_from_paths with exact parity
    refs_p, sel_p, pf_p = MukhaPresenter.intake_from_paths([pasted])
    assert len(refs_p) == 2
    assert pf_p.eligible_count == 2


def test_cli_intake_uses_effective_sutra_roots_and_prevents_self_ingestion(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Proves CLI resolves effective roots from configuration and excludes them from ingestion."""
    rt_dir = tmp_path / "ConfiguredRuntime"
    out_dir = tmp_path / "ConfiguredOutput"
    rt_dir.mkdir(parents=True)
    out_dir.mkdir(parents=True)

    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        f'[storage]\nruntime_root = "{rt_dir.as_posix()}"\noutput_root = "{out_dir.as_posix()}"\n',
        encoding="utf-8",
    )

    bad_staging_file = rt_dir / "staged_leak.txt"
    bad_staging_file.write_text("leak", encoding="utf-8")

    argv = ["--config", str(settings_file), "--input", str(bad_staging_file)]
    exit_code = cli_main(argv)
    assert exit_code == 2

    captured = capsys.readouterr()
    assert "Validation error:" in captured.err
    assert "overlap" in captured.err.lower() or "runtime" in captured.err.lower()
    # Verify raw secret path is never printed
    assert str(tmp_path) not in captured.err


# ---------------------------------------------------------------------------
# 2. Cancellation Token Strict Validation & Reconciliation
# ---------------------------------------------------------------------------


def test_cancellation_token_type_validation() -> None:
    """Proves Request and ExecutionContext strictly validate cancellation_token types."""
    with pytest.raises(TypeError, match="cancellation_token must be a CancellationToken instance or None"):
        Request(
            request_id="req-1",
            requirement="read_native",
            inputs=(InputRef("inp-1", Path("test.txt"), "test.txt", 10),),
            cancellation_token="invalid_token_string",  # type: ignore
        )

    with pytest.raises(TypeError, match="cancellation_token must be a CancellationToken instance or None"):
        ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            cancellation_token=12345,  # type: ignore
        )


def test_cancellation_token_reconciliation_at_agni_entry(tmp_path: Path) -> None:
    """Proves Agni reconciles request and context tokens and rejects conflicting distinct tokens."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("content", encoding="utf-8")

    t1 = CancellationToken()
    t2 = CancellationToken()

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        capabilities={"read_native": MockSuccessCapability()},
    )

    req = Request(
        request_id="req-recon-1",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 7),),
        cancellation_token=t1,
    )
    conflicting_ctx = ExecutionContext(
        run_id="run-recon-1",
        request_id="req-recon-1",
        trace_id="tr-1",
        span_id="sp-1",
        cancellation_token=t2,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req, context=conflicting_ctx)
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED
    assert "Conflicting distinct cancellation tokens" in exc_info.value.message


# ---------------------------------------------------------------------------
# 3. Continuation Request Token Preservation & Retry/Quarantine Bypass
# ---------------------------------------------------------------------------


def test_continuation_preserves_cancellation_token_and_bypasses_retry(tmp_path: Path) -> None:
    """Proves continuation Request retains cancellation_token and cancellation bypasses retry policy."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("content", encoding="utf-8")
    token = CancellationToken()

    class Stage1ContinuationCap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            # Cancel during stage 1
            token.cancel()
            doc = CanonicalDocument(
                document_id="doc-1",
                source_input_id=request.inputs[0].input_id,
                text="STAGE 1",
                pages=(),
                tables=(),
            )
            return Result(data=doc, next_requirement="ocr")

    class Stage2ShouldNotRunCap:
        def __init__(self) -> None:
            from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION
            self.executed = False

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            self.executed = True
            return Result(data=prior_result.data if prior_result else None)

    stage2 = Stage2ShouldNotRunCap()
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        capabilities={"read_native": Stage1ContinuationCap(), "ocr": stage2},
    )

    req = Request(
        request_id="req-cont-cancel",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 7),),
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    assert exc_info.value.code is FailureCode.EXECUTION_FAILED
    assert exc_info.value.context.get("cancelled") is True
    assert stage2.executed is False


def test_cancellation_after_capability_execution_produces_cancelled_outcome(tmp_path: Path) -> None:
    """Proves cancellation occurring immediately after capability returns produces cancelled outcome, not success."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("content", encoding="utf-8")
    token = CancellationToken()

    class StageCancelOnReturnCap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            doc = CanonicalDocument(
                document_id="doc-1",
                source_input_id=request.inputs[0].input_id,
                text="SUCCESSFUL TEXT",
                pages=(),
                tables=(),
            )
            # Cancel at the very end of capability execution
            token.cancel()
            return Result(data=doc)

    out_root = tmp_path / "Output"
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=out_root,
        capabilities={"read_native": StageCancelOnReturnCap()},
    )

    req = Request(
        request_id="req-cancel-race",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 7),),
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    assert exc_info.value.context.get("cancelled") is True
    manifests = list(out_root.glob("**/run-manifest.json"))
    assert len(manifests) == 1
    manifest_dict = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest_dict["status"] == "cancelled"


# ---------------------------------------------------------------------------
# 4. Artifact Semantics on Failure and Cancellation
# ---------------------------------------------------------------------------


def test_cancelled_run_cleans_ordinary_committed_artifacts(tmp_path: Path) -> None:
    """Proves ordinary committed artifacts are removed upon cancellation, keeping only partial/ when requested."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("content", encoding="utf-8")
    token = CancellationToken()

    class ArtifactProducerCancelCap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            from sarathi.sankalpa import ArtifactIntent, ArtifactPayload

            payload = ArtifactPayload(
                intent=ArtifactIntent(name="pages.json", role="pages", media_type="application/json"),
                content=b'{"pages": 1}',
            )
            token.cancel()
            return Result(data="data", artifact_payloads=(payload,))

    out_root = tmp_path / "Output"
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=out_root,
        capabilities={"read_native": ArtifactProducerCancelCap()},
    )

    req = Request(
        request_id="req-art-cancel",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 7),),
        cancellation_token=token,
        preserve_partial=False,
    )

    with pytest.raises(DoshError):
        agni.execute(req)

    manifest_file = list(out_root.glob("**/run-manifest.json"))[0]
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "cancelled"
    assert len(manifest_data["artifacts"]) == 0
    # No committed artifact file exists on disk
    assert not (manifest_file.parent / "pages.json").exists()


# ---------------------------------------------------------------------------
# 5. Safe Retained History Schema, Non-Coercion, and Bounded Store
# ---------------------------------------------------------------------------


def test_terminal_run_summary_strict_from_dict_and_validation() -> None:
    """Proves TerminalRunSummary rejects type coercion and unsafe values."""
    valid_dict = {
        "run_id": "run-001",
        "request_id": "req-001",
        "requirement": "read_native",
        "profile": "instant",
        "status": "completed",
        "start_time_utc": "2026-09-02T12:00:00Z",
        "completed_at_utc": "2026-09-02T12:00:01Z",
        "duration_ms": 1000,
        "artifact_count": 2,
        "warning_count": 0,
        "has_masked_identity": False,
        "output_dir": "read_native/Run-1",
    }
    summary = TerminalRunSummary.from_dict(valid_dict)
    assert summary.run_id == "run-001"

    # Reject string for duration_ms (no int coercion)
    bad_duration = dict(valid_dict, duration_ms="1000")
    with pytest.raises(TypeError, match="Field 'duration_ms' must be an integer"):
        TerminalRunSummary.from_dict(bad_duration)

    # Reject boolean for artifact_count
    bad_art_count = dict(valid_dict, artifact_count=True)
    with pytest.raises(TypeError, match="Field 'artifact_count' must be an integer"):
        TerminalRunSummary.from_dict(bad_art_count)

    # Reject path traversal in output_dir
    bad_out_dir = dict(valid_dict, output_dir="../unsafe/path")
    with pytest.raises(ValueError, match="output_dir must be a safe relative run reference"):
        TerminalRunSummary.from_dict(bad_out_dir)


def test_history_store_bounds_enforcement_jsonl_and_sqlite(tmp_path: Path) -> None:
    """Proves history store caps records at max_records in both JSONL and SQLite formats."""
    # 1. JSONL Store
    jsonl_path = tmp_path / "history.jsonl"
    store_jsonl = TerminalRunHistoryStore(jsonl_path, format="jsonl", max_records=3)

    for i in range(5):
        s = TerminalRunSummary(
            run_id=f"run-{i:03d}",
            request_id=f"req-{i:03d}",
            requirement="read_native",
            profile="instant",
            status="completed",
            start_time_utc="2026-09-02T12:00:00Z",
            completed_at_utc=f"2026-09-02T12:00:0{i}Z",
            duration_ms=100,
            artifact_count=0,
            warning_count=0,
        )
        assert store_jsonl.save(s) is True

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert "run-004" in lines[-1]
    assert len(store_jsonl.query(limit=10)) == 3

    # 2. SQLite Store
    db_path = tmp_path / "history.db"
    store_sqlite = TerminalRunHistoryStore(db_path, format="sqlite", max_records=3)

    for i in range(5):
        s = TerminalRunSummary(
            run_id=f"run-db-{i:03d}",
            request_id=f"req-db-{i:03d}",
            requirement="read_native",
            profile="instant",
            status="completed",
            start_time_utc="2026-09-02T12:00:00Z",
            completed_at_utc=f"2026-09-02T12:00:0{i}Z",
            duration_ms=100,
            artifact_count=0,
            warning_count=0,
        )
        assert store_sqlite.save(s) is True

    results = store_sqlite.query(limit=10)
    assert len(results) == 3
    assert results[0].run_id == "run-db-004"


def test_darpana_observable_history_persistence_failure(tmp_path: Path) -> None:
    """Proves history save failure sets safe observable state in Darpana without breaking document processing."""
    darpana = Darpana(capacity=100, history_path=tmp_path / "history.jsonl", history_format="jsonl")
    assert darpana.history_persistence_failed is False

    summary = TerminalRunSummary(
        run_id="run-fail-save",
        request_id="req-fail-save",
        requirement="read_native",
        profile="instant",
        status="completed",
        start_time_utc="2026-09-02T12:00:00Z",
        completed_at_utc="2026-09-02T12:00:01Z",
        duration_ms=100,
        artifact_count=0,
        warning_count=0,
    )

    with patch.object(TerminalRunHistoryStore, "save", return_value=False):
        darpana.record_run_summary(summary)

    assert darpana.history_persistence_failed is True
    marutis = darpana.maruti_records()
    assert any(m.phase_name == "telemetry.history_persistence_failure" and m.outcome == "failure" for m in marutis)


# ---------------------------------------------------------------------------
# 6. Additional Regression Tests: Darshana Token, Request ID Spaces, Path Bounds
# ---------------------------------------------------------------------------


def test_identify_request_preserves_cancellation_token_object_identity(tmp_path: Path) -> None:
    """Proves identify_request preserves cancellation_token by object identity."""
    from sarathi.shakti.darshana.identifier import identify_request

    doc_file = tmp_path / "doc.txt"
    doc_file.write_text("sample content", encoding="utf-8")

    token = CancellationToken()
    request = Request(
        request_id="req-token-id",
        requirement="read_native",
        inputs=(InputRef("inp-1", doc_file, "doc.txt", doc_file.stat().st_size),),
        cancellation_token=token,
    )

    enriched = identify_request(request)
    assert enriched.cancellation_token is request.cancellation_token
    assert enriched.cancellation_token is token


def test_request_id_with_spaces_succeeds_end_to_end(tmp_path: Path) -> None:
    """Proves request IDs with spaces succeed end-to-end and do not fail history recording."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("sample content", encoding="utf-8")

    settings = Settings(
        data={
            "telemetry": {
                "history_enabled": True,
                "history_format": "jsonl",
            }
        }
    )

    out_root = tmp_path / "Output"
    agni = Agni(
        settings=settings,
        runtime_root=tmp_path / "Runtime",
        output_root=out_root,
        capabilities={"read_native": MockSuccessCapability()},
    )

    req = Request(
        request_id="req-my monthly report",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 14),),
    )

    res = agni.execute(req)
    assert res.data is not None

    # Confirmed artifacts and manifests exist
    manifests = list(out_root.glob("**/run-manifest.json"))
    assert len(manifests) == 1
    m_dict = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert m_dict["status"] == "completed"


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

    # Seed oversized file with 50 pre-existing records
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

    # Store configured with max_records=5
    store = TerminalRunHistoryStore(jsonl_path, format="jsonl", max_records=5)

    # Save a 51st record
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

    # File must now contain strictly only the bounded tail (5 records)
    remaining_lines = [ln.strip() for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(remaining_lines) == 5
    assert "run-new-001" in remaining_lines[-1]

    # Query with limit=3 returns only 3 most recent
    queried = store.query(limit=3)
    assert len(queried) == 3
    assert queried[0].run_id == "run-new-001"
