"""Unit tests for cancellation semantics, OPERATION_CANCELLED failure code, and Maruti telemetry."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.agni import Agni
from sarathi.darpana import Darpana, MarutiRecord
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    CapabilityDeclaration,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PluginInfo,
    Request,
    Result,
)
from sarathi.sutra import Settings


class HangingOrCancelledCapability:
    """Test capability that checks cancellation during execution."""

    def __init__(self, cancel_during: bool = False) -> None:
        self.declaration = CapabilityDeclaration(
            capability_id="cancel_cap",
            plugin_id="cancel.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        self.cancel_during = cancel_during
        self.call_count = 0

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.call_count += 1
        if self.cancel_during and context.cancellation_token is not None:
            context.cancellation_token.cancel()
        if context.cancellation_token is not None:
            context.cancellation_token.check_cancelled()
        return Result(data="should_not_reach")


class TestCancellationSemantics:
    def test_token_raises_operation_cancelled(self) -> None:
        token = CancellationToken()
        assert not token.is_cancelled
        token.check_cancelled()  # No error when not cancelled

        token.cancel()
        assert token.is_cancelled
        with pytest.raises(DoshError) as exc_info:
            token.check_cancelled()
        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED

    def test_maruti_record_allows_cancelled_outcome(self) -> None:
        rec = MarutiRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="t-1",
            span_id="s-1",
            phase_name="test_phase",
            component="test_comp",
            timestamp_utc="2026-09-05T00:00:00Z",
            duration_ns=1000,
            outcome="cancelled",
            failure_code=FailureCode.OPERATION_CANCELLED,
        )
        assert rec.outcome == "cancelled"
        assert rec.failure_code == FailureCode.OPERATION_CANCELLED

    def test_darpana_time_scope_records_cancelled_outcome(self) -> None:
        darpana = Darpana()
        token = CancellationToken()
        token.cancel()
        ctx = ExecutionContext(
            run_id="run-c",
            request_id="req-c",
            trace_id="t-c",
            span_id="s-c",
            cancellation_token=token,
        )

        with pytest.raises(DoshError) as exc_info:
            with darpana.time_scope(ctx, "exec_phase", "test_comp"):
                token.check_cancelled()

        assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
        records = darpana.maruti_records()
        assert len(records) == 1
        assert records[0].outcome == "cancelled"
        assert records[0].failure_code == FailureCode.OPERATION_CANCELLED

    def test_pravaha_does_not_retry_or_quarantine_on_cancellation(self, tmp_path: Path) -> None:
        in_dir = tmp_path / "inputs"
        out_dir = tmp_path / "outputs"
        rt_dir = tmp_path / "runtime"
        in_dir.mkdir()
        out_dir.mkdir()
        rt_dir.mkdir()

        test_file = in_dir / "sample.txt"
        test_file.write_text("sample content", encoding="utf-8")

        settings = Settings({
            "storage": {
                "input_root": str(in_dir),
                "output_root": str(out_dir),
                "runtime_root": str(rt_dir),
            },
            "pipeline": {
                "max_retries": 3,
            },
        })

        cap = HangingOrCancelledCapability(cancel_during=True)
        plugin = PluginInfo(
            plugin_id="cancel.plugin",
            name="Cancel Plugin",
            version="1.0.0",
            capabilities=("cancel_cap",),
        )

        agni = Agni(
            settings=settings,
            capabilities={"cancel_cap": cap},
            plugins=[plugin],
        )
        try:
            token = CancellationToken()
            req = Request(
                request_id="req-cancel-1",
                requirement="cancel_cap",
                inputs=(
                    InputRef(
                        input_id="inp-1",
                        source_path=test_file,
                        display_name="sample.txt",
                        size_bytes=len(test_file.read_bytes()),
                    ),
                ),
                cancellation_token=token,
            )

            with pytest.raises(DoshError) as exc_info:
                agni.execute(req)

            assert exc_info.value.code == FailureCode.OPERATION_CANCELLED
            # Proves it was only called once, never retried despite max_retries=3
            assert cap.call_count == 1

            # Proves no quarantine records created for cancelled operations
            quarantine_dir = rt_dir / "Quarantine"
            if quarantine_dir.exists():
                manifests = list(quarantine_dir.glob("*/manifest.json"))
                assert len(manifests) == 0
        finally:
            agni.close()
