"""Unit tests for Darpana - Telemetry & Tracing Service in Sarathi V2."""

from pathlib import Path
from typing import Any

import pytest

from sarathi.darpana import (
    AccuracyValue,
    Darpana,
    MarutiRecord,
    PramanaRecord,
)
from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import (
    ArtifactBoundary,
    CapabilityPlan,
    Dvara,
    Kosh,
    Manthan,
    Pravaha,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import (
    ArtifactIntent,
    CapabilityDeclaration,
    ConfidenceValue,
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PluginInfo,
    ProvenanceRecord,
    Request,
    Result,
    SecurityDeclaration,
)
from sarathi.shakti.darshana import DarshanaCapability
from sarathi.shakti.native_extraction import NativeExtractionCapability
from sarathi.shakti.ocr import OCRCapability
from sarathi.sutra import load_settings
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


@pytest.fixture
def execution_context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-123",
        request_id="req-456",
        trace_id="tr-789",
        span_id="sp-001",
    )


class TestMarutiTelemetry:
    def test_maruti_record_immutability_and_attributes(self) -> None:
        rec = MarutiRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            phase_name="ocr_page",
            component="shakti.ocr",
            timestamp_utc="2026-09-01T00:00:00Z",
            duration_ns=150_000_000,
            outcome="success",
            attributes={"page_idx": 1},
        )
        assert rec.run_id == "run-1"
        assert rec.phase_name == "ocr_page"
        assert rec.duration_ns == 150_000_000
        assert rec.outcome == "success"
        assert rec.error_type is None
        assert rec.failure_code is None
        assert rec.attributes["page_idx"] == 1

        with pytest.raises(TypeError):
            rec.attributes["page_idx"] = 2  # type: ignore

    def test_maruti_record_validation(self) -> None:
        with pytest.raises(ValueError, match="run_id must be a non-empty string"):
            MarutiRecord(
                run_id="",
                request_id="req-1",
                trace_id="tr-1",
                span_id="sp-1",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="success",
            )

        with pytest.raises(TypeError, match="duration_ns must be an integer"):
            MarutiRecord(
                run_id="run-1",
                request_id="req-1",
                trace_id="tr-1",
                span_id="sp-1",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns="100",  # type: ignore
                outcome="success",
            )

        with pytest.raises(ValueError, match="duration_ns cannot be negative"):
            MarutiRecord(
                run_id="run-1",
                request_id="req-1",
                trace_id="tr-1",
                span_id="sp-1",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=-5,
                outcome="success",
            )

        with pytest.raises(ValueError, match="outcome must be 'success' or 'failure'"):
            MarutiRecord(
                run_id="run-1",
                request_id="req-1",
                trace_id="tr-1",
                span_id="sp-1",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="unknown_status",
            )

        with pytest.raises(TypeError, match="failure_code must be a FailureCode or None"):
            MarutiRecord(
                run_id="run-1",
                request_id="req-1",
                trace_id="tr-1",
                span_id="sp-1",
                phase_name="p",
                component="c",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="failure",
                error_type="DoshError",
                failure_code="INVALID_STRING_CODE",  # type: ignore
            )

    def test_time_scope_success(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with darpana.time_scope(
            execution_context,
            phase_name="native_extraction",
            component="shakti.native_extraction",
            attributes={"format": "pdf"},
        ):
            x = 1 + 1
            assert x == 2

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.run_id == execution_context.run_id
        assert rec.request_id == execution_context.request_id
        assert rec.trace_id == execution_context.trace_id
        assert rec.span_id == execution_context.span_id
        assert rec.phase_name == "native_extraction"
        assert rec.component == "shakti.native_extraction"
        assert rec.outcome == "success"
        assert rec.error_type is None
        assert rec.failure_code is None
        assert rec.duration_ns >= 0
        assert rec.attributes["format"] == "pdf"

    def test_time_scope_records_dosh_failure_code_safely(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with pytest.raises(DoshError) as exc_info:
            with darpana.time_scope(
                execution_context,
                phase_name="ocr",
                component="shakti.ocr",
            ):
                raise DoshError(FailureCode.EXECUTION_FAILED, "Secret sensitive execution error text")

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "DoshError"
        assert rec.failure_code is FailureCode.EXECUTION_FAILED
        assert rec.duration_ns >= 0
        # Privacy check: sensitive message is not recorded in error_type, failure_code or attributes
        assert "Secret sensitive execution error text" not in str(rec.error_type)
        assert "Secret sensitive execution error text" not in str(rec.failure_code)
        assert "Secret sensitive execution error text" not in str(rec.attributes)

    def test_time_scope_standard_exception_has_no_failure_code(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with pytest.raises(ValueError, match="Standard value error"):
            with darpana.time_scope(
                execution_context,
                phase_name="process",
                component="shakti.native",
            ):
                raise ValueError("Standard value error")

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "ValueError"
        assert rec.failure_code is None
        assert rec.duration_ns >= 0

    def test_time_scope_validates_before_executing_wrapped_work(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)
        executed = False

        with pytest.raises(TypeError, match="attributes must be a Mapping or None"):
            with darpana.time_scope(
                execution_context,
                phase_name="extract",
                component="shakti.native_extraction",
                attributes="invalid_string_attributes",  # type: ignore
            ):
                executed = True

        assert executed is False
        assert len(darpana.maruti_records()) == 0


class TestPramanaTelemetry:
    def test_accuracy_value_ratio_and_evidence(self) -> None:
        acc = AccuracyValue(
            score=0.92,
            method="ground_truth_cer_levenshtein",
            evidence={"evaluated_chars": 1500, "errors": 120},
        )
        assert acc.score == 0.92
        assert acc.as_ratio == 0.92
        assert acc.as_percent == 92.0
        assert acc.method == "ground_truth_cer_levenshtein"
        assert acc.evidence["evaluated_chars"] == 1500

    def test_pramana_record_with_confidence_and_accuracy(self) -> None:
        conf = ConfidenceValue(
            score=0.95,
            method="ocr_char_probabilities",
            evidence={"min": 0.8},
        )
        acc = AccuracyValue(
            score=0.98,
            method="exact_cell_comparison",
            evidence={"cells": 100},
        )
        rec = PramanaRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="ocr",
            stage="page_recognition",
            timestamp_utc="2026-09-01T00:00:00Z",
            subject_id="page_1",
            confidence=conf,
            accuracy=acc,
            attributes={"lang": "hi"},
        )
        assert rec.capability_id == "ocr"
        assert rec.confidence == conf
        assert rec.accuracy == acc
        assert rec.subject_id == "page_1"


class TestDarpanaService:
    def test_bounded_history_eviction(self) -> None:
        darpana = Darpana(capacity=3)
        assert darpana.capacity == 3

        for i in range(5):
            rec = MarutiRecord(
                run_id=f"run-{i}",
                request_id="req",
                trace_id="tr",
                span_id="sp",
                phase_name="test",
                component="comp",
                timestamp_utc="2026-09-01T00:00:00Z",
                duration_ns=100,
                outcome="success",
            )
            darpana.record_maruti(rec)

        records = darpana.maruti_records()
        assert len(records) == 3
        assert [r.run_id for r in records] == ["run-2", "run-3", "run-4"]


class MockTelemetryCapability:
    """Mock capability for telemetry integration testing."""

    def __init__(
        self,
        declaration: CapabilityDeclaration,
        *,
        fail_error: BaseException | None = None,
        confidence: ConfidenceValue | None = None,
        accuracy: AccuracyValue | None = None,
    ) -> None:
        self.declaration = declaration
        self.fail_error = fail_error
        self.confidence = confidence
        self.accuracy = accuracy
        self.call_count = 0

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.call_count += 1
        if self.fail_error is not None:
            raise self.fail_error
        meta: dict[str, Any] = {}
        if self.accuracy is not None:
            meta["accuracy"] = self.accuracy
        return Result(
            data=f"{self.declaration.capability_id}_output",
            confidence=self.confidence,
            provenance=(
                ProvenanceRecord(
                    stage=self.declaration.capability_id,
                    evidence={"test": "evidence"},
                ),
            ),
            metadata=meta,
        )


class TestDarpanaGlobalWiring:
    """Rigorous acceptance tests for Darpana Maruti & Pramana global wiring across canonical boundaries."""

    def test_yantra_allocate_invalid_requirement_fails_before_telemetry(
        self, execution_context: ExecutionContext
    ) -> None:
        darpana = Darpana(capacity=10)
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
        yantra = Yantra(inventory, darpana=darpana)

        with pytest.raises(TypeError, match="requirement must be a DeviceRequirement instance"):
            yantra.allocate("invalid_requirement_string", context=execution_context)  # type: ignore

        # Zero telemetry records created on invalid argument
        assert len(darpana.maruti_records()) == 0

    def test_yantra_release_invalid_allocation_fails_before_telemetry(
        self, execution_context: ExecutionContext
    ) -> None:
        darpana = Darpana(capacity=10)
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
        yantra = Yantra(inventory, darpana=darpana)

        with pytest.raises(TypeError, match="allocation must be an Allocation instance"):
            yantra.release("invalid_allocation_string", context=execution_context)  # type: ignore

        assert len(darpana.maruti_records()) == 0

    def test_successful_end_to_end_pipeline_maruti_and_pramana_wiring(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        darpana = Darpana(capacity=50)

        # 1. Dvara Bootstrap
        kosh = Kosh()
        dvara = Dvara(kosh, darpana=darpana)
        dvara.register_builtins(context=execution_context)

        # 2. Sutra loader
        conf_file = tmp_path / "settings.toml"
        conf_file.write_text("[pipeline]\nmax_retries = 2\n", encoding="utf-8")
        settings = load_settings(conf_file, darpana=darpana, context=execution_context)
        assert settings.get_section("pipeline")["max_retries"] == 2

        # 3. Yantra & Pravaha setup
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
        yantra = Yantra(inventory, darpana=darpana)
        manthan = Manthan(kosh)

        ocr_decl = kosh.get_capability("ocr")
        assert ocr_decl is not None

        ocr_conf = ConfidenceValue(
            score=0.96,
            method="rapidocr_mean",
            evidence={"engine": "rapidocr", "page_count": 1},
        )
        ocr_cap = MockTelemetryCapability(ocr_decl, confidence=ocr_conf)

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"ocr": ocr_cap},
            darpana=darpana,
        )

        # 4. ArtifactBoundary setup
        runtime_root = tmp_path / "Runtime"
        output_root = tmp_path / "Output"
        art_boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, darpana=darpana)
        workspace = art_boundary.begin_run(
            run_id=execution_context.run_id,
            requirement="ocr",
            context=execution_context,
        )

        intent = ArtifactIntent(name="report.txt", role="report", media_type="text/plain", relative_path="report.txt")
        workspace.commit_artifact(intent, b"Sample committed text")

        # 5. Pipeline execution
        request = Request(
            request_id=execution_context.request_id,
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("input.png"),
                    display_name="input.png",
                    size_bytes=500,
                ),
            ),
        )
        plan = CapabilityPlan(request_id=request.request_id, capability_ids=("ocr",))

        result = pravaha.execute(plan, request, execution_context)
        assert result.data == "ocr_output"

        # 6. Artifact finalization
        workspace.finalize(success=True, context=execution_context)

        # 7. Inspect all collected Maruti records
        maruti_records = darpana.maruti_records()
        phase_names = [r.phase_name for r in maruti_records]

        assert "bootstrap" in phase_names
        assert "configuration" in phase_names
        assert "allocation" in phase_names
        assert "capability_execution" in phase_names
        assert "release" in phase_names
        assert "pipeline_stage" in phase_names
        assert "artifact_finalization" in phase_names

        for r in maruti_records:
            assert r.run_id == execution_context.run_id
            assert r.request_id == execution_context.request_id
            assert r.trace_id == execution_context.trace_id
            assert r.outcome == "success"
            assert r.error_type is None
            assert r.failure_code is None
            assert r.duration_ns >= 0

        # 8. Inspect Pramana records
        pramana_records = darpana.pramana_records()
        assert len(pramana_records) == 1
        p_rec = pramana_records[0]
        assert p_rec.capability_id == "ocr"
        assert p_rec.confidence == ocr_conf

    def test_failed_run_records_correlated_failure_code_in_maruti(
        self,
        execution_context: ExecutionContext,
    ) -> None:
        darpana = Darpana(capacity=20)
        kosh = Kosh()
        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.pipeline",
                name="Pipe",
                version="1.0.0",
                security=SecurityDeclaration(),
                capabilities=("extract",),
            )
        )
        extract_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
        )
        kosh.register_capability(extract_decl)

        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
        yantra = Yantra(inventory, darpana=darpana)
        manthan = Manthan(kosh)

        failing_cap = MockTelemetryCapability(
            extract_decl,
            fail_error=DoshError(FailureCode.EXECUTION_FAILED, "Secret sensitive failure text"),
        )
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": failing_cap},
            darpana=darpana,
        )

        request = Request(
            request_id=execution_context.request_id,
            requirement="extract",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="doc.pdf",
                    size_bytes=100,
                ),
            ),
        )
        plan = CapabilityPlan(request_id=request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, request, execution_context)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED

        maruti_records = darpana.maruti_records()
        failed_records = [r for r in maruti_records if r.outcome == "failure"]
        assert len(failed_records) >= 1

        for fr in failed_records:
            assert fr.run_id == execution_context.run_id
            assert fr.request_id == execution_context.request_id
            assert fr.error_type == "DoshError"
            assert fr.failure_code is FailureCode.EXECUTION_FAILED
            assert "Secret sensitive failure text" not in str(fr.error_type)
            assert "Secret sensitive failure text" not in str(fr.attributes)

    def test_quarantine_lifecycle_telemetry_observations_quarantined_retried_released_terminal(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        darpana = Darpana(capacity=50)
        kosh = Kosh()
        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.pipeline",
                name="Pipe",
                version="1.0.0",
                security=SecurityDeclaration(),
                capabilities=("extract",),
            )
        )
        extract_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
        )
        kosh.register_capability(extract_decl)

        class FlakyTelemetryCapability(MockTelemetryCapability):
            def execute(
                self, request: Request, context: ExecutionContext, prior_result: Result | None = None
            ) -> Result:
                self.call_count += 1
                if self.call_count == 1:
                    raise DoshError(FailureCode.EXECUTION_FAILED, "Temporary flake")
                return Result(
                    data="flaky_success",
                    confidence=ConfidenceValue(score=0.9, method="test", evidence={"try": 2}),
                )

        flaky_cap = FlakyTelemetryCapability(extract_decl)
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
        yantra = Yantra(inventory, darpana=darpana)
        manthan = Manthan(kosh)
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=2)

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": flaky_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
            darpana=darpana,
        )

        request = Request(
            request_id=execution_context.request_id,
            requirement="extract",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="doc.pdf",
                    size_bytes=100,
                ),
            ),
        )
        plan = CapabilityPlan(request_id=request.request_id, capability_ids=("extract",))

        result = pravaha.execute(plan, request, execution_context)
        assert result.data == "flaky_success"
        assert flaky_cap.call_count == 2

        maruti_records = darpana.maruti_records()
        quar_obs = [r for r in maruti_records if r.phase_name == "quarantine_lifecycle"]

        # Transitions: quarantined -> retried -> released
        statuses = [r.attributes["lifecycle_status"] for r in quar_obs]
        assert "quarantined" in statuses
        assert "retried" in statuses
        assert "released" in statuses

        # Verify factual non-negative measured durations and safe attributes only
        for r in quar_obs:
            assert r.duration_ns >= 0
            assert r.outcome == "success"
            assert "capability_id" in r.attributes
            assert "attempt_count" in r.attributes
            assert "max_retries" in r.attributes
            assert "lifecycle_status" in r.attributes
            assert "doc.pdf" not in str(r.attributes)

    def test_exhausted_retry_observes_terminal_quarantine_outcome(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        darpana = Darpana(capacity=50)
        kosh = Kosh()
        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.pipeline",
                name="Pipe",
                version="1.0.0",
                security=SecurityDeclaration(),
                capabilities=("extract",),
            )
        )
        extract_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
        )
        kosh.register_capability(extract_decl)

        always_fail_cap = MockTelemetryCapability(
            extract_decl,
            fail_error=DoshError(FailureCode.EXECUTION_FAILED, "Permanent failure"),
        )
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )
        yantra = Yantra(inventory, darpana=darpana)
        manthan = Manthan(kosh)
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=1)

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": always_fail_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
            darpana=darpana,
        )

        request = Request(
            request_id=execution_context.request_id,
            requirement="extract",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="doc.pdf",
                    size_bytes=100,
                ),
            ),
        )
        plan = CapabilityPlan(request_id=request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError):
            pravaha.execute(plan, request, execution_context)

        maruti_records = darpana.maruti_records()
        quar_obs = [r for r in maruti_records if r.phase_name == "quarantine_lifecycle"]
        statuses = [r.attributes["lifecycle_status"] for r in quar_obs]

        # Initial quarantine -> retry attempt -> terminal exhaustion
        assert "quarantined" in statuses
        assert "retried" in statuses
        assert "terminal" in statuses

    def test_capabilities_never_create_timers_or_telemetry_instances(self) -> None:
        for cap_cls in (DarshanaCapability, NativeExtractionCapability, OCRCapability):
            inst = cap_cls()
            assert not hasattr(inst, "darpana")
            assert not hasattr(inst, "timer")
            assert not hasattr(inst, "recorder")
            assert not hasattr(inst, "telemetry")
