"""Focused Adversarial Tests for Cancellation, Token Reconciliation, and Staging Cleanup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sarathi.agni import Agni
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

    assert exc_info.value.code is FailureCode.OPERATION_CANCELLED
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
    assert not (manifest_file.parent / "pages.json").exists()


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

    manifests = list(out_root.glob("**/run-manifest.json"))
    assert len(manifests) == 1
    m_dict = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert m_dict["status"] == "completed"


def test_cancellation_bypasses_retry_in_pravaha() -> None:
    """Triggered cancellation token immediately raises error before retry execution."""
    from unittest.mock import MagicMock

    from sarathi.nabhi.kosh import Kosh
    from sarathi.nabhi.manthan import Manthan
    from sarathi.nabhi.pravaha import Pravaha
    from sarathi.nabhi.quarantine import QuarantineRecord, QuarantineStatus, QuarantineStore
    from sarathi.sankalpa import CapabilityDeclaration, ExecutionProfile, PluginInfo
    from sarathi.yantra import Yantra

    token = CancellationToken()
    token.cancel()

    kosh = Kosh()
    plugin_info = PluginInfo(plugin_id="test_plugin", name="Test", version="1.0.0", capabilities=("test_cap",))
    cap_decl = CapabilityDeclaration(
        capability_id="test_cap",
        plugin_id="test_plugin",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT,),
    )
    kosh.register_plugin(plugin_info)
    kosh.register_capability(cap_decl)

    manthan = Manthan(registry=kosh)
    yantra = Yantra(inventory=Yantra.default_inventory())
    quar_store_mock = MagicMock(spec=QuarantineStore)

    cap_mock = MagicMock()
    cap_mock.declaration = cap_decl

    pravaha = Pravaha(
        manthan=manthan,
        yantra=yantra,
        capabilities={"test_cap": cap_mock},
        quarantine_store=quar_store_mock,
    )

    rec = QuarantineRecord(
        quarantine_id="quar-123",
        input_hash="hash123",
        run_id="run1",
        request_id="req1",
        trace_id="tr1",
        capability_id="test_cap",
        plugin_id="test_plugin",
        failure_code=FailureCode.EXECUTION_FAILED,
        profile="instant",
        attempt_count=0,
        max_retries=2,
        status=QuarantineStatus.QUARANTINED,
        created_at_utc="2026-01-01T00:00:00Z",
        updated_at_utc="2026-01-01T00:00:00Z",
    )

    ctx = ExecutionContext(
        run_id="run1", request_id="req1", trace_id="tr1", span_id="sp1", cancellation_token=token
    )
    req = Request(
        request_id="req1",
        requirement="test_cap",
        inputs=(InputRef("inp-1", Path("test.txt"), "test.txt", 10),),
        cancellation_token=token,
    )

    with pytest.raises(DoshError) as exc_info:
        pravaha._execute_retry_attempt(cap_mock, req, ctx, rec)

    assert exc_info.value.code is FailureCode.OPERATION_CANCELLED
    assert exc_info.value.context.get("cancelled") is True

