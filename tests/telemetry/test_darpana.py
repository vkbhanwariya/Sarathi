"""Unit tests for Darpana - Telemetry & Tracing Service in Sarathi V2."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pytest

import sarathi.darpana as darpana_module
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
    Capability,
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
    WarningRecord,
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

    def test_time_scope_success(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with darpana.time_scope(
            execution_context,
            phase_name="native_extraction",
            component="shakti.native_extraction",
            attributes={"format": "pdf"},
        ):
            # simulate work
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
        assert rec.duration_ns >= 0
        assert rec.attributes["format"] == "pdf"

    def test_time_scope_failure_and_privacy(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with pytest.raises(ValueError, match="Confidential sensitive error details"):
            with darpana.time_scope(
                execution_context,
                phase_name="ocr",
                component="shakti.ocr",
            ):
                raise ValueError("Confidential sensitive error details")

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "ValueError"
        assert rec.duration_ns >= 0
        # Privacy check: sensitive message is not recorded in error_type or attributes
        assert "Confidential sensitive error details" not in rec.error_type
        assert "Confidential sensitive error details" not in str(rec.attributes)

    def test_time_scope_records_keyboard_interrupt_and_reraises(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)

        with pytest.raises(KeyboardInterrupt):
            with darpana.time_scope(
                execution_context,
                phase_name="process",
                component="shakti.bank_statements",
            ):
                raise KeyboardInterrupt()

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "KeyboardInterrupt"
        assert rec.duration_ns >= 0

    def test_time_scope_validates_before_executing_wrapped_work(self, execution_context: ExecutionContext) -> None:
        darpana = Darpana(capacity=10)
        executed = False

        # Invalid attributes type must raise TypeError before entering work block
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

        # Invalid empty phase_name
        with pytest.raises(ValueError, match="phase_name must be a non-empty string"):
            with darpana.time_scope(
                execution_context,
                phase_name="  ",
                component="comp",
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

        with pytest.raises(TypeError):
            acc.evidence["errors"] = 0  # type: ignore

    def test_accuracy_value_validation(self) -> None:
        with pytest.raises(TypeError, match="cannot be a boolean"):
            AccuracyValue(score=True, method="cer", evidence={"n": 1})

        with pytest.raises(TypeError, match="must be numeric"):
            AccuracyValue(score="0.9", method="cer", evidence={"n": 1})  # type: ignore

        with pytest.raises(ValueError, match="cannot be NaN or Inf"):
            AccuracyValue(score=float("nan"), method="cer", evidence={"n": 1})

        with pytest.raises(ValueError, match="ratio in range"):
            AccuracyValue(score=92.0, method="cer", evidence={"n": 1})

        with pytest.raises(ValueError, match="ratio in range"):
            AccuracyValue(score=-0.01, method="cer", evidence={"n": 1})

        with pytest.raises(ValueError, match="non-empty string"):
            AccuracyValue(score=0.9, method="   ", evidence={"n": 1})

        with pytest.raises(ValueError, match="non-empty mapping"):
            AccuracyValue(score=0.9, method="cer", evidence={})

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

    def test_pramana_record_unavailable_defaults_stay_none(self) -> None:
        rec = PramanaRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="darshana",
            stage="identify",
            timestamp_utc="2026-09-01T00:00:00Z",
        )
        assert rec.confidence is None
        assert rec.accuracy is None
        assert rec.subject_id is None


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
        # Oldest 0, 1 evicted, remaining are 2, 3, 4
        assert [r.run_id for r in records] == ["run-2", "run-3", "run-4"]
        assert isinstance(records, tuple)

    def test_darpana_pramana_recording_and_snapshot(self) -> None:
        darpana = Darpana(capacity=5)
        rec = PramanaRecord(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            capability_id="ocr",
            stage="read",
            timestamp_utc="2026-09-01T00:00:00Z",
        )
        darpana.record_pramana(rec)

        pramana_recs = darpana.pramana_records()
        assert len(pramana_recs) == 1
        assert pramana_recs[0] == rec
        assert isinstance(pramana_recs, tuple)

    def test_darpana_explicit_capacity_required(self) -> None:
        # Default capacity removed: constructor must reject no arguments
        with pytest.raises(TypeError):
            Darpana()  # type: ignore

        with pytest.raises(TypeError, match="capacity must be an integer"):
            Darpana(capacity="100")  # type: ignore

        with pytest.raises(ValueError, match="capacity must be a positive integer"):
            Darpana(capacity=0)

    def test_darpana_exports(self) -> None:
        expected = {"AccuracyValue", "Darpana", "MarutiRecord", "PramanaRecord"}
        assert set(darpana_module.__all__) == expected
        for name in expected:
            assert hasattr(darpana_module, name)


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

    def test_successful_end_to_end_pipeline_maruti_and_pramana_wiring(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        # 1. Initialize shared bounded Darpana service
        darpana = Darpana(capacity=50)

        # 2. Bootstrap boundary: Dvara
        kosh = Kosh()
        dvara = Dvara(kosh, darpana=darpana)
        dvara.register_builtins(context=execution_context)

        # Verify bootstrap Maruti record
        m_recs = darpana.maruti_records()
        assert len(m_recs) == 1
        assert m_recs[0].phase_name == "bootstrap"
        assert m_recs[0].component == "nabhi.dvara"
        assert m_recs[0].outcome == "success"
        assert m_recs[0].run_id == execution_context.run_id

        # 3. Configuration boundary: Sutra loader
        conf_file = tmp_path / "settings.toml"
        conf_file.write_text('[pipeline]\nmax_retries = 2\n', encoding="utf-8")
        settings = load_settings(conf_file, darpana=darpana, context=execution_context)
        assert settings.get_section("pipeline")["max_retries"] == 2

        m_recs = darpana.maruti_records()
        assert len(m_recs) == 2
        assert m_recs[1].phase_name == "configuration"
        assert m_recs[1].component == "sutra.loader"
        assert m_recs[1].outcome == "success"

        # 4. Yantra & Pravaha setup with Darpana injection
        inventory = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
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

        # 5. ArtifactBoundary setup with Darpana injection
        runtime_root = tmp_path / "Runtime"
        output_root = tmp_path / "Output"
        art_boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root, darpana=darpana)
        workspace = art_boundary.begin_run(
            run_id=execution_context.run_id,
            requirement="ocr",
            context=execution_context,
        )

        # Commit an artifact
        intent = ArtifactIntent(name="report.txt", role="report", media_type="text/plain", relative_path="report.txt")
        workspace.commit_artifact(intent, b"Sample committed text")

        # 6. Pipeline execution
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

        # 7. Artifact finalization
        workspace.finalize(success=True, context=execution_context)

        # 8. Inspect all collected Maruti records
        maruti_records = darpana.maruti_records()
        phase_names = [r.phase_name for r in maruti_records]

        # Must contain all canonical boundaries:
        assert "bootstrap" in phase_names
        assert "configuration" in phase_names
        assert "allocation" in phase_names
        assert "capability_execution" in phase_names
        assert "release" in phase_names
        assert "pipeline_stage" in phase_names
        assert "artifact_finalization" in phase_names

        # All records must share the exact correlation identity
        for r in maruti_records:
            assert r.run_id == execution_context.run_id
            assert r.request_id == execution_context.request_id
            assert r.trace_id == execution_context.trace_id
            assert r.outcome == "success"
            assert r.error_type is None
            assert r.duration_ns >= 0

        # 9. Inspect Pramana records
        pramana_records = darpana.pramana_records()
        assert len(pramana_records) == 1
        p_rec = pramana_records[0]
        assert p_rec.run_id == execution_context.run_id
        assert p_rec.request_id == execution_context.request_id
        assert p_rec.trace_id == execution_context.trace_id
        assert p_rec.capability_id == "ocr"
        assert p_rec.stage == "ocr"
        assert p_rec.confidence == ocr_conf
        assert p_rec.accuracy is None  # Unavailable stays unavailable

    def test_failed_run_records_correlated_failure_in_maruti(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
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

        inventory = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
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
            # Privacy check: secret text is never placed into error_type or attributes
            assert "Secret sensitive failure text" not in str(fr.error_type)
            assert "Secret sensitive failure text" not in str(fr.attributes)

    def test_retry_lifecycle_telemetry_recording(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        darpana = Darpana(capacity=30)
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
            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                self.call_count += 1
                if self.call_count == 1:
                    raise DoshError(FailureCode.EXECUTION_FAILED, "Temporary flake")
                return Result(
                    data="flaky_success",
                    confidence=ConfidenceValue(score=0.9, method="test", evidence={"try": 2}),
                )

        flaky_cap = FlakyTelemetryCapability(extract_decl)
        inventory = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
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
        retry_records = [r for r in maruti_records if r.phase_name == "retry_attempt"]
        assert len(retry_records) == 1
        assert retry_records[0].outcome == "success"
        assert retry_records[0].attributes["attempt"] == 1
        assert retry_records[0].attributes["max_retries"] == 2

        # Pramana record from retry success
        pramana_records = darpana.pramana_records()
        assert len(pramana_records) == 1
        assert pramana_records[0].confidence is not None
        assert pramana_records[0].confidence.score == 0.9

    def test_missing_confidence_stays_unavailable(
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

        # Capability returns no confidence
        cap = MockTelemetryCapability(extract_decl, confidence=None)
        inventory = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
        yantra = Yantra(inventory, darpana=darpana)
        manthan = Manthan(kosh)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
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
        assert result.confidence is None

        # No fabricated pramana record
        assert len(darpana.pramana_records()) == 0

    def test_pramana_accuracy_evidence_recording(
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

        acc = AccuracyValue(
            score=0.99,
            method="reference_ground_truth_comparison",
            evidence={"matched_tokens": 990, "total_tokens": 1000},
        )
        cap = MockTelemetryCapability(extract_decl, accuracy=acc)

        inventory = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])
        yantra = Yantra(inventory, darpana=darpana)
        manthan = Manthan(kosh)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
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
        assert result.metadata.get("accuracy") == acc

        pramana_recs = darpana.pramana_records()
        assert len(pramana_recs) == 1
        assert pramana_recs[0].accuracy == acc
        assert pramana_recs[0].confidence is None

    def test_capabilities_never_create_timers_or_telemetry_instances(self) -> None:
        """Verify capabilities implement only the pure Capability protocol without telemetry handles."""
        for cap_cls in (DarshanaCapability, NativeExtractionCapability, OCRCapability):
            inst = cap_cls()
            assert not hasattr(inst, "darpana")
            assert not hasattr(inst, "timer")
            assert not hasattr(inst, "recorder")
            assert not hasattr(inst, "telemetry")

    def test_darpana_safe_privacy_no_path_or_secret_leakage(
        self,
        execution_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        darpana = Darpana(capacity=50)

        # Context manager recording with confidential secret
        secret_path = tmp_path / "secret_document.pdf"
        secret_path.write_bytes(b"TOP SECRET CONTENT")

        with pytest.raises(DoshError):
            with darpana.time_scope(
                execution_context,
                phase_name="pipeline_stage",
                component="nabhi.pravaha",
                attributes={"action": "test_confidential"},
            ):
                raise DoshError(
                    FailureCode.SECURITY_DENIED,
                    f"Access denied to file {secret_path} with secret data",
                )

        records = darpana.maruti_records()
        assert len(records) == 1
        rec = records[0]
        assert rec.outcome == "failure"
        assert rec.error_type == "DoshError"

        # Verify raw path / raw content / raw message is NOT in the record
        rec_repr = repr(rec).lower()
        assert "secret_document.pdf" not in rec_repr
        assert "top secret content" not in rec_repr
        assert "access denied to file" not in rec_repr
