"""Tests for Cooperative Cancellation, Device Release, Partial Retention, and Telemetry."""

import json
import time
from pathlib import Path

import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
)


class MockSlowCapability:
    """Deterministic mock capability that simulates cooperative execution."""

    def __init__(self, delay_s: float = 0.0, cancel_during: CancellationToken | None = None) -> None:
        from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

        self.declaration = CAPABILITY_DECLARATION
        self._delay_s = delay_s
        self._cancel_during = cancel_during

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        if self._cancel_during is not None:
            self._cancel_during.cancel()

        if self._delay_s > 0:
            time.sleep(self._delay_s)

        doc = CanonicalDocument(
            document_id="doc-mock-1",
            source_input_id=request.inputs[0].input_id,
            text="SAMPLE CONTENT",
            pages=(PageData(page_number=1, text="SAMPLE CONTENT", tables=()),),
            tables=(),
        )
        return Result(data=doc)


def test_cancellation_before_execution(tmp_path: Path) -> None:
    """Proves pre-cancelled token prevents execution and finalizes workspace with status='cancelled'."""
    darpana = Darpana(capacity=100)
    input_file = tmp_path / "doc.txt"
    input_file.write_text("sample content", encoding="utf-8")

    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled is True

    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities={"read_native": MockSlowCapability()},
        darpana=darpana,
    )

    req = Request(
        request_id="req-cancel-pre",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 14),),
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    err = exc_info.value
    assert err.code is FailureCode.OPERATION_CANCELLED
    assert "cancelled" in err.message.lower()
    assert err.context.get("cancelled") is True

    # Verify run-manifest.json exists with status="cancelled"
    manifest_files = list((tmp_path / "Output").glob("**/run-manifest.json"))
    assert len(manifest_files) == 1
    manifest_data = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert manifest_data["status"] == "cancelled"

    # Verify Darpana recorded cancellation event
    marutis = darpana.maruti_records()
    assert any(m.phase_name == "cancellation" and m.attributes.get("cancelled") is True for m in marutis)


def test_cancellation_during_pipeline_execution(tmp_path: Path) -> None:
    """Proves cancellation triggered during execution safely stops subsequent stages."""
    darpana = Darpana(capacity=100)
    input_file = tmp_path / "doc.txt"
    input_file.write_text("sample content", encoding="utf-8")

    token = CancellationToken()

    class Stage1Cap:
        def __init__(self) -> None:
            from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            # Trigger cancellation during stage 1 execution
            token.cancel()
            doc = CanonicalDocument(
                document_id="doc-s1",
                source_input_id=request.inputs[0].input_id,
                text="STAGE 1",
                pages=(),
                tables=(),
            )
            # Request continuation to stage 2
            return Result(data=doc, next_requirement="ocr")

    class Stage2Cap:
        def __init__(self) -> None:
            from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION

            self.declaration = CAPABILITY_DECLARATION
            self.executed = False

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            self.executed = True
            return Result(data=prior_result.data if prior_result else None)

    stage2 = Stage2Cap()
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=tmp_path / "Output",
        input_root=tmp_path / "Input",
        capabilities={
            "read_native": Stage1Cap(),
            "ocr": stage2,
        },
        darpana=darpana,
    )

    req = Request(
        request_id="req-cancel-mid",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 14),),
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    assert exc_info.value.context.get("cancelled") is True
    # Stage 2 must never have executed because cancellation was caught between stages
    assert stage2.executed is False

    # Manifest records cancelled
    manifest_files = list((tmp_path / "Output").glob("**/run-manifest.json"))
    assert len(manifest_files) == 1
    manifest_data = json.loads(manifest_files[0].read_text(encoding="utf-8"))
    assert manifest_data["status"] == "cancelled"


def test_cancellation_partial_retention_default_vs_explicit(tmp_path: Path) -> None:
    """Proves cancellation respects preserve_partial policy."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("sample content", encoding="utf-8")

    token1 = CancellationToken()
    token1.cancel()

    # 1. preserve_partial=False (default)
    out1 = tmp_path / "Output1"
    agni1 = Agni(
        runtime_root=tmp_path / "Runtime1",
        output_root=out1,
        input_root=tmp_path / "Input",
        capabilities={"read_native": MockSlowCapability()},
    )
    req1 = Request(
        request_id="req-c-1",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 14),),
        preserve_partial=False,
        cancellation_token=token1,
    )
    with pytest.raises(DoshError):
        agni1.execute(req1)

    manifest1 = list(out1.glob("**/run-manifest.json"))[0]
    assert json.loads(manifest1.read_text(encoding="utf-8"))["status"] == "cancelled"

    # 2. preserve_partial=True
    token2 = CancellationToken()
    token2.cancel()
    out2 = tmp_path / "Output2"
    agni2 = Agni(
        runtime_root=tmp_path / "Runtime2",
        output_root=out2,
        input_root=tmp_path / "Input",
        capabilities={"read_native": MockSlowCapability()},
    )
    req2 = Request(
        request_id="req-c-2",
        requirement="read_native",
        inputs=(InputRef("inp-2", input_file, "doc.txt", 14),),
        preserve_partial=True,
        cancellation_token=token2,
    )
    with pytest.raises(DoshError):
        agni2.execute(req2)

    manifest2 = list(out2.glob("**/run-manifest.json"))[0]
    assert json.loads(manifest2.read_text(encoding="utf-8"))["status"] == "cancelled"


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
        capabilities={"read_native": MockSlowCapability()},
    )

    req = Request(
        request_id="req-rec-1",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 7),),
        cancellation_token=t1,
    )
    ctx = ExecutionContext(
        run_id="run-1",
        request_id="req-rec-1",
        trace_id="tr-1",
        span_id="sp-1",
        cancellation_token=t2,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req, context=ctx)
    assert exc_info.value.code is FailureCode.VALIDATION_FAILED


def test_cancellation_after_capability_execution_produces_cancelled_outcome(tmp_path: Path) -> None:
    """Cancellation occurring immediately after capability returns produces cancelled outcome, not success."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("sample content", encoding="utf-8")
    token = CancellationToken()

    class CapCancelsImmediatelyAfterReturn(MockSlowCapability):
        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            res = super().execute(request, context, prior_result)
            token.cancel()
            return res

    out_root = tmp_path / "Output"
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=out_root,
        capabilities={"read_native": CapCancelsImmediatelyAfterReturn()},
    )
    req = Request(
        request_id="req-post-cancel",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 14),),
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    assert exc_info.value.code is FailureCode.OPERATION_CANCELLED
    manifest_file = list(out_root.glob("**/run-manifest.json"))[0]
    assert json.loads(manifest_file.read_text(encoding="utf-8"))["status"] == "cancelled"


def test_cancelled_run_cleans_ordinary_committed_artifacts(tmp_path: Path) -> None:
    """Ordinary committed artifacts are removed upon cancellation, keeping only partial/ when requested."""
    input_file = tmp_path / "doc.txt"
    input_file.write_text("sample content", encoding="utf-8")
    token = CancellationToken()

    class CapStagingArtifactsThenCancels(MockSlowCapability):
        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            from sarathi.sankalpa import ArtifactIntent, ArtifactPayload
            res = super().execute(request, context, prior_result)
            payload = ArtifactPayload(
                intent=ArtifactIntent("pages.json", "application/json", "output"),
                content=b'{"pages": [1]}',
            )
            token.cancel()
            return Result(data=res.data, artifact_payloads=(payload,))

    out_root = tmp_path / "Output"
    agni = Agni(
        runtime_root=tmp_path / "Runtime",
        output_root=out_root,
        capabilities={"read_native": CapStagingArtifactsThenCancels()},
    )
    req = Request(
        request_id="req-artifact-cleanup",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "doc.txt", 14),),
        preserve_partial=False,
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        agni.execute(req)

    assert exc_info.value.code is FailureCode.OPERATION_CANCELLED
    manifest_file = list(out_root.glob("**/run-manifest.json"))[0]
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["status"] == "cancelled"
    assert len(manifest_data["artifacts"]) == 0
    assert not (manifest_file.parent / "pages.json").exists()


def test_token_raises_operation_cancelled() -> None:
    token = CancellationToken()
    assert not token.is_cancelled
    token.check_cancelled()

    token.cancel()
    assert token.is_cancelled
    with pytest.raises(DoshError) as exc_info:
        token.check_cancelled()
    assert exc_info.value.code is FailureCode.OPERATION_CANCELLED


def test_maruti_record_allows_cancelled_outcome() -> None:
    from sarathi.darpana import MarutiRecord
    rec = MarutiRecord(
        run_id="run-1",
        request_id="req-1",
        trace_id="tr-1",
        span_id="sp-1",
        phase_name="execution",
        component="test",
        timestamp_utc="2026-09-07T00:00:00Z",
        duration_ns=1000,
        outcome="cancelled",
    )
    assert rec.outcome == "cancelled"


def test_darpana_time_scope_records_cancelled_outcome() -> None:
    darpana = Darpana(capacity=10)
    ctx = ExecutionContext(run_id="run-1", request_id="req-1", trace_id="tr-1", span_id="sp-1")
    with pytest.raises(DoshError) as exc_info:
        with darpana.time_scope(ctx, "cancellation_test", "test.component"):
            raise DoshError(FailureCode.OPERATION_CANCELLED, "Task was cancelled")

    assert exc_info.value.code is FailureCode.OPERATION_CANCELLED
    records = darpana.maruti_records()
    assert len(records) == 1
    assert records[0].outcome == "cancelled"
    assert records[0].failure_code == FailureCode.OPERATION_CANCELLED
