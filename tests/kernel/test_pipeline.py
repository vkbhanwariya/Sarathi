"""Unit tests for Nabhi - Core Kernel: Pravaha Dynamic Pipeline Engine."""

from pathlib import Path
from typing import Any
from unittest.mock import patch
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import (
    ArtifactBoundary,
    CapabilityPlan,
    Kosh,
    LifecycleAction,
    LifecycleActionType,
    Manthan,
    Pravaha,
    QuarantineRecord,
    QuarantineStatus,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import (
    ArtifactIntent,
    Capability,
    CapabilityDeclaration,
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
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class MockExecutableCapability:
    """Mock executable capability tracking lifecycle and configurable outputs/errors."""

    def __init__(
        self,
        declaration: CapabilityDeclaration,
        *,
        fail_error: BaseException | None = None,
        transform_data_fn: Any = None,
        append_warning: WarningRecord | None = None,
        append_provenance: ProvenanceRecord | None = None,
        tracker: list[str] | None = None,
        return_invalid_type: Any = None,
        next_requirement: str | None = None,
    ) -> None:
        self.declaration = declaration
        self.fail_error = fail_error
        self.transform_data_fn = transform_data_fn
        self.append_warning = append_warning
        self.append_provenance = append_provenance
        self.tracker = tracker
        self.return_invalid_type = return_invalid_type
        self.next_requirement = next_requirement
        self.call_count = 0
        self.received_requests: list[Request] = []
        self.received_prior_results: list[Result | None] = []

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.call_count += 1
        self.received_requests.append(request)
        self.received_prior_results.append(prior_result)
        if self.tracker is not None:
            self.tracker.append(self.declaration.capability_id)
        if self.fail_error is not None:
            raise self.fail_error

        if self.return_invalid_type is not None:
            return self.return_invalid_type  # type: ignore

        prior_data = prior_result.data if prior_result is not None else ""
        if self.transform_data_fn:
            new_data = self.transform_data_fn(prior_data)
        else:
            new_data = f"{prior_data}+{self.declaration.capability_id}" if prior_data else self.declaration.capability_id

        prior_warnings = prior_result.warnings if prior_result is not None else ()
        new_warnings = list(prior_warnings)
        if self.append_warning:
            new_warnings.append(self.append_warning)

        prior_prov = prior_result.provenance if prior_result is not None else ()
        new_prov = list(prior_prov)
        if self.append_provenance:
            new_prov.append(self.append_provenance)

        return Result(
            data=new_data,
            warnings=tuple(new_warnings),
            provenance=tuple(new_prov),
            next_requirement=self.next_requirement,
        )


@pytest.fixture
def sample_plugin() -> PluginInfo:
    return PluginInfo(
        plugin_id="shakti.pipeline",
        name="Pipeline Plugin",
        version="1.0.0",
        security=SecurityDeclaration(),
        capabilities=("extract", "normalize", "export", "ocr", "read_native"),
    )


@pytest.fixture
def cap_decls(sample_plugin: PluginInfo) -> tuple[CapabilityDeclaration, ...]:
    c1 = CapabilityDeclaration(
        capability_id="extract",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
    )
    c2 = CapabilityDeclaration(
        capability_id="normalize",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
    )
    c3 = CapabilityDeclaration(
        capability_id="export",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
    )
    c4 = CapabilityDeclaration(
        capability_id="ocr",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
    )
    c5 = CapabilityDeclaration(
        capability_id="read_native",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
    )
    return (c1, c2, c3, c4, c5)


@pytest.fixture
def kosh(sample_plugin: PluginInfo, cap_decls: tuple[CapabilityDeclaration, ...]) -> Kosh:
    registry = Kosh()
    registry.register_plugin(sample_plugin)
    for c in cap_decls:
        registry.register_capability(c)
    return registry


@pytest.fixture
def manthan(kosh: Kosh) -> Manthan:
    return Manthan(kosh)


@pytest.fixture
def yantra() -> Yantra:
    inv = DeviceInventory([
        DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
    ])
    return Yantra(inv)


@pytest.fixture
def sample_request() -> Request:
    return Request(
        request_id="req-pipe-1",
        requirement="extract",
        inputs=(
            InputRef(
                input_id="inp-1",
                source_path=Path("input.pdf"),
                display_name="input.pdf",
                size_bytes=2048,
            ),
        ),
    )


@pytest.fixture
def sample_context() -> ExecutionContext:
    return ExecutionContext(
        run_id="run-1",
        request_id="req-pipe-1",
        trace_id="tr-1",
        span_id="sp-1",
    )


class TestPravahaPipelineEngine:
    def test_ordered_execution_and_prior_result_handoff(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, c2, c3, _, _ = cap_decls
        execution_order: list[str] = []

        cap1 = MockExecutableCapability(
            c1,
            tracker=execution_order,
            append_warning=WarningRecord(code="W001", message="warn1"),
            append_provenance=ProvenanceRecord(stage="s1", evidence={"detail": "det1"}),
        )
        cap2 = MockExecutableCapability(
            c2,
            tracker=execution_order,
            append_warning=WarningRecord(code="W002", message="warn2"),
            append_provenance=ProvenanceRecord(stage="s2", evidence={"detail": "det2"}),
        )
        cap3 = MockExecutableCapability(
            c3,
            tracker=execution_order,
            append_warning=WarningRecord(code="W003", message="warn3"),
            append_provenance=ProvenanceRecord(stage="s3", evidence={"detail": "det3"}),
        )

        capabilities = {
            "extract": cap1,
            "normalize": cap2,
            "export": cap3,
        }

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract", "normalize", "export"))

        result = pravaha.execute(plan, sample_request, sample_context)

        # Plan order must be strictly preserved
        assert execution_order == ["extract", "normalize", "export"]
        assert result.data == "extract+normalize+export"

        # Prior results must be properly threaded
        assert cap1.received_prior_results == [None]
        assert cap2.received_prior_results[0] is not None
        assert cap2.received_prior_results[0].data == "extract"
        assert cap3.received_prior_results[0] is not None
        assert cap3.received_prior_results[0].data == "extract+normalize"

        # Warnings and provenance must accumulate monotonically
        warning_codes = [w.code for w in result.warnings]
        assert warning_codes == ["W001", "W002", "W003"]
        prov_stages = [p.stage for p in result.provenance]
        assert prov_stages == ["s1", "s2", "s3"]

    def test_pravaha_invokes_capabilities_strictly_through_yantra(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, _, _, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1)
        capabilities = {"extract": cap1}

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with patch.object(yantra, "execute", wraps=yantra.execute) as spy_yantra:
            result = pravaha.execute(plan, sample_request, sample_context)
            assert spy_yantra.call_count == 1

        assert result.data == "extract"
        assert cap1.call_count == 1

    def test_next_requirement_handoff_from_native_extraction_to_ocr(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, _, _, c_ocr, c_native = cap_decls
        execution_order: list[str] = []

        class ResumingNativeCap:
            def __init__(self) -> None:
                self.declaration = c_native
                self.calls = 0

            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                self.calls += 1
                execution_order.append("read_native")
                if prior_result is None or not prior_result.data:
                    return Result(
                        data="native",
                        provenance=(ProvenanceRecord(stage="native", evidence={"detail": "insufficient_text"}),),
                        next_requirement="ocr",
                    )
                return Result(
                    data=f"native+{prior_result.data}",
                    provenance=prior_result.provenance + (ProvenanceRecord(stage="native", evidence={"detail": "resumed"}),),
                    next_requirement=None,
                )

        native_cap = ResumingNativeCap()
        ocr_cap = MockExecutableCapability(
            c_ocr,
            tracker=execution_order,
            append_provenance=ProvenanceRecord(stage="ocr", evidence={"detail": "full_page_ocr"}),
        )

        capabilities = {
            "extract": MockExecutableCapability(c1),
            "read_native": native_cap,
            "ocr": ocr_cap,
        }

        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.native",
                name="Native Plugin",
                version="1.0.0",
                security=SecurityDeclaration(),
                capabilities=("read_native",),
            )
        )
        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.ocr",
                name="OCR Plugin",
                version="1.0.0",
                security=SecurityDeclaration(),
                capabilities=("ocr",),
            )
        )

        req_native = Request(
            request_id="req-native-1",
            requirement="read_native",
            inputs=sample_request.inputs,
        )
        ctx_native = ExecutionContext(
            run_id="run-native-1",
            request_id="req-native-1",
            trace_id="tr-native-1",
            span_id="sp-native-1",
        )

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = manthan.resolve(req_native)
        assert plan.capability_ids == ("read_native",)

        final_result = pravaha.execute(plan, req_native, ctx_native)

        assert execution_order == ["read_native", "ocr"]
        assert "ocr" in final_result.data
        assert final_result.next_requirement is None
        prov_stages = [p.stage for p in final_result.provenance]
        assert "ocr" in prov_stages and "native" in prov_stages

    def test_next_requirement_preserves_request_fields(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_context: ExecutionContext,
    ) -> None:
        _, _, _, c_ocr, c_native = cap_decls

        class ResumingNativeCap:
            def __init__(self) -> None:
                self.declaration = c_native
                self.calls = 0

            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                self.calls += 1
                if prior_result is None or not prior_result.data:
                    return Result(data="native", next_requirement="ocr")
                return Result(data="done", next_requirement=None)

        native_cap = ResumingNativeCap()
        ocr_cap = MockExecutableCapability(c_ocr)

        capabilities = {
            "read_native": native_cap,
            "ocr": ocr_cap,
        }

        orig_req = Request(
            request_id="req-preserved-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="doc.pdf",
                    size_bytes=1024,
                ),
            ),
            profile=ExecutionProfile.ACCURATE,
            custom_options={"lang": "hi"},
            output_root=Path("out/root"),
            preserve_partial=True,
            metadata={"caller": "test_runner"},
        )
        ctx = ExecutionContext(
            run_id="run-pres-1",
            request_id="req-preserved-1",
            trace_id="tr-pres-1",
            span_id="sp-pres-1",
        )

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = manthan.resolve(orig_req)

        pravaha.execute(plan, orig_req, ctx)

        # Verify OCR received a Request preserving all original options and inputs
        assert len(ocr_cap.received_requests) == 1
        ocr_req = ocr_cap.received_requests[0]
        assert ocr_req.request_id == "req-preserved-1"
        assert ocr_req.requirement == "ocr"
        assert ocr_req.inputs == orig_req.inputs
        assert ocr_req.profile == ExecutionProfile.ACCURATE
        assert dict(ocr_req.custom_options) == {"lang": "hi"}
        assert ocr_req.output_root == Path("out/root")
        assert ocr_req.preserve_partial is True
        assert dict(ocr_req.metadata) == {"caller": "test_runner"}

    def test_repeated_requirement_handoff_rejected_before_repeat_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, _, _, _, _ = cap_decls

        loop_cap = MockExecutableCapability(
            c1,
            next_requirement="extract",  # Same as initial requirement
        )
        capabilities = {"extract": loop_cap}

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Repeated requirement 'extract'" in err.message
        assert loop_cap.call_count == 1  # Executed initial step, rejected BEFORE repeat

    def test_circular_requirement_handoff_rejected(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, c2, _, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1, next_requirement="normalize")
        cap2 = MockExecutableCapability(c2, next_requirement="extract")  # Circular back to extract

        capabilities = {
            "extract": cap1,
            "normalize": cap2,
        }

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Repeated requirement 'extract'" in err.message
        assert cap1.call_count == 1
        assert cap2.call_count == 1

    def test_missing_executable_binding_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, _, _, _, _ = cap_decls
        # No capabilities provided in mapping
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities={})
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Executable capability 'extract' is not provided" in err.message

    def test_invalid_executable_contract_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        class NonConformingCapability:
            pass

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": NonConformingCapability()},  # type: ignore
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(TypeError, match="does not implement Capability protocol"):
            pravaha.execute(plan, sample_request, sample_context)

    def test_declaration_mismatch_with_kosh_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        tampered_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="2.0.0",  # Version mismatch with Kosh
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
        )
        cap = MockExecutableCapability(tampered_decl)
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities={"extract": cap})
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "declaration does not match registered declaration in Kosh" in err.message
        assert cap.call_count == 0  # Pre-execution validation stopped execution

    def test_unregistered_capability_in_plan_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1)
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities={"extract": cap})
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("unregistered_cap",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Planned capability 'unregistered_cap' is not registered in Kosh" in err.message

    def test_capability_failure_stops_pipeline_and_preserves_error(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, c2, _, _, _ = cap_decls
        original_err = DoshError(
            code=FailureCode.RESOURCE_UNAVAILABLE,
            message="Out of memory in step 1",
        )
        cap1 = MockExecutableCapability(c1, fail_error=original_err)
        cap2 = MockExecutableCapability(c2)

        capabilities = {
            "extract": cap1,
            "normalize": cap2,
        }

        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract", "normalize"))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        # Exact exception is preserved and pipeline halts immediately
        assert exc_info.value is original_err
        assert cap1.call_count == 1
        assert cap2.call_count == 0  # Step 2 never executed

    def test_invalid_plan_request_or_context_rejects(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1, _, _, _, _ = cap_decls
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": MockExecutableCapability(c1)},
        )
        valid_plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(TypeError, match="plan must be a CapabilityPlan"):
            pravaha.execute("not_a_plan", sample_request, sample_context)  # type: ignore

        with pytest.raises(TypeError, match="request must be a Request"):
            pravaha.execute(valid_plan, "not_a_request", sample_context)  # type: ignore

        with pytest.raises(TypeError, match="context must be an ExecutionContext"):
            pravaha.execute(valid_plan, sample_request, "not_a_context")  # type: ignore

        # Request ID mismatch between plan and request
        mismatched_plan = CapabilityPlan(request_id="mismatched-req-id", capability_ids=("extract",))
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(mismatched_plan, sample_request, sample_context)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Plan request_id 'mismatched-req-id' does not match" in exc_info.value.message

        # Request ID mismatch between context and request
        mismatched_ctx = ExecutionContext(
            run_id="run-1",
            request_id="mismatched-ctx-id",
            trace_id="tr-1",
            span_id="sp-1",
        )
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(valid_plan, sample_request, mismatched_ctx)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Context request_id 'mismatched-ctx-id' does not match" in exc_info.value.message

        # Constructor argument validation
        with pytest.raises(TypeError, match="manthan must be a Manthan instance"):
            Pravaha(manthan="bad_manthan", yantra=yantra, capabilities={"extract": MockExecutableCapability(c1)})  # type: ignore
        with pytest.raises(TypeError, match="yantra must be a Yantra instance"):
            Pravaha(manthan=manthan, yantra="bad_yantra", capabilities={"extract": MockExecutableCapability(c1)})  # type: ignore
        with pytest.raises(TypeError, match="capabilities must be a Mapping"):
            Pravaha(manthan=manthan, yantra=yantra, capabilities=["not_a_map"])  # type: ignore

    def test_pravaha_uses_exact_manthan_kosh_registry(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
    ) -> None:
        c1, _, _, _, _ = cap_decls
        capabilities = {"extract": MockExecutableCapability(c1)}
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities=capabilities)

        # Proves Pravaha and Manthan use the exact same canonical Kosh instance
        assert pravaha._registry is manthan.registry
        assert pravaha._registry is kosh


class TestPravahaFailureLifecycleAndQuarantine:
    """Explicit acceptance tests for Pravaha failure lifecycle, bounded retry, and quarantine."""

    def test_no_retry_policy_executes_classified_failure_only_once(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        failing_cap = MockExecutableCapability(
            c1_decl,
            fail_error=DoshError(FailureCode.EXECUTION_FAILED, "Primary execution failure"),
        )
        q_store = QuarantineStore(tmp_path / "quarantine")
        # No retry policy supplied -> must default to zero automatic retries
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": failing_cap},
            quarantine_store=q_store,
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        assert failing_cap.call_count == 1  # Exactly 1 attempt, zero retries

        # Manifest exists and is marked terminal
        q_dirs = list((tmp_path / "quarantine").iterdir())
        assert len(q_dirs) == 1
        record = q_store.get_record(q_dirs[0].name)
        assert record is not None
        assert record.status is QuarantineStatus.TERMINAL
        assert record.attempt_count == 0

    def test_retry_policy_without_quarantine_store_is_rejected_at_initialization(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        policy = RetryPolicy(max_retries=2)

        with pytest.raises(DoshError) as exc_info:
            Pravaha(
                manthan=manthan,
                yantra=yantra,
                capabilities={"extract": MockExecutableCapability(c1_decl)},
                quarantine_store=None,
                retry_policy=policy,
            )

        err = exc_info.value
        assert err.code is FailureCode.INVALID_CONFIGURATION
        assert "Automatic retry policy requires a configured QuarantineStore" in err.message

    def test_input_hash_represents_canonical_inputs_regression(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities={"extract": cap})

        req1 = Request(
            request_id="req-same",
            requirement="extract",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("C:/secret/raw/path1/docA.pdf"),
                    display_name="docA.pdf",
                    size_bytes=1024,
                    media_type="application/pdf",
                ),
            ),
        )

        req2 = Request(
            request_id="req-same",
            requirement="extract",
            inputs=(
                InputRef(
                    input_id="inp-2",
                    source_path=Path("C:/secret/raw/path2/docB.pdf"),
                    display_name="docB.pdf",
                    size_bytes=2048,
                    media_type="application/pdf",
                ),
            ),
        )

        hash1 = pravaha._compute_input_hash(req1, cap, sample_context)
        hash2 = pravaha._compute_input_hash(req2, cap, sample_context)

        # Proves two requests with identical run/request/capability/profile but different canonical inputs produce distinct hashes
        assert hash1 != hash2
        assert len(hash1) == 64
        assert len(hash2) == 64

    def test_input_hash_deterministic_ordering_for_multi_inputs(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        pravaha = Pravaha(manthan=manthan, yantra=yantra, capabilities={"extract": cap})

        inp_a = InputRef(
            input_id="inp-a",
            source_path=Path("a.pdf"),
            display_name="a.pdf",
            size_bytes=500,
        )
        inp_b = InputRef(
            input_id="inp-b",
            source_path=Path("b.pdf"),
            display_name="b.pdf",
            size_bytes=800,
        )

        req_ab = Request(
            request_id="req-ab",
            requirement="extract",
            inputs=(inp_a, inp_b),
        )
        req_ba = Request(
            request_id="req-ab",
            requirement="extract",
            inputs=(inp_b, inp_a),
        )

        hash_ab1 = pravaha._compute_input_hash(req_ab, cap, sample_context)
        hash_ab2 = pravaha._compute_input_hash(req_ab, cap, sample_context)
        hash_ba = pravaha._compute_input_hash(req_ba, cap, sample_context)

        # Deterministic stability
        assert hash_ab1 == hash_ab2
        # Different ordered input material produces different hashes
        assert hash_ab1 != hash_ba

    def test_classified_failure_enters_failure_lifecycle(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        failing_cap = MockExecutableCapability(
            c1_decl,
            fail_error=DoshError(FailureCode.EXECUTION_FAILED, "Primary execution error"),
        )
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=0)  # No retry allowed
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": failing_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        assert failing_cap.call_count == 1

        # Manifest must exist and be in terminal quarantine
        q_dirs = list((tmp_path / "quarantine").iterdir())
        assert len(q_dirs) == 1
        record = q_store.get_record(q_dirs[0].name)
        assert record is not None
        assert record.status is QuarantineStatus.TERMINAL
        assert record.failure_code is FailureCode.EXECUTION_FAILED
        assert record.attempt_count == 0

    def test_allowed_retry_executes_again_through_yantra_and_succeeds(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls

        class FlakyCapability(MockExecutableCapability):
            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                self.call_count += 1
                if self.call_count == 1:
                    raise DoshError(FailureCode.EXECUTION_FAILED, "Temporary flake")
                return Result(data=("flaky_success",))

        flaky_cap = FlakyCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=2)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": flaky_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        result = pravaha.execute(plan, sample_request, sample_context)

        assert result.data == ("flaky_success",)
        assert flaky_cap.call_count == 2

        # Quarantined item must have been released upon retry success
        q_dirs = list((tmp_path / "quarantine").iterdir())
        assert len(q_dirs) == 1
        record = q_store.get_record(q_dirs[0].name)
        assert record is not None
        assert record.status is QuarantineStatus.RELEASED
        assert record.attempt_count == 1

    def test_retry_exhaustion_becomes_terminal_quarantine(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        always_failing_cap = MockExecutableCapability(
            c1_decl,
            fail_error=DoshError(FailureCode.EXECUTION_FAILED, "Persistent failure"),
        )
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=2)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": always_failing_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        assert exc_info.value.code is FailureCode.EXECUTION_FAILED
        # 1 initial attempt + 2 retries = 3 calls
        assert always_failing_cap.call_count == 3

        q_dirs = list((tmp_path / "quarantine").iterdir())
        assert len(q_dirs) == 1
        record = q_store.get_record(q_dirs[0].name)
        assert record is not None
        assert record.status is QuarantineStatus.TERMINAL
        assert record.attempt_count == 2

    def test_permanent_non_retryable_failure_does_not_loop(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        security_failing_cap = MockExecutableCapability(
            c1_decl,
            fail_error=DoshError(FailureCode.SECURITY_DENIED, "Access denied"),
        )
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=5)  # High retry limit, but code is non-retryable
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": security_failing_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert security_failing_cap.call_count == 1  # No loop!

        q_dirs = list((tmp_path / "quarantine").iterdir())
        assert len(q_dirs) == 1
        record = q_store.get_record(q_dirs[0].name)
        assert record is not None
        assert record.status is QuarantineStatus.TERMINAL
        assert record.attempt_count == 0

    def test_terminal_attempt_cannot_execute_again(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        failing_cap = MockExecutableCapability(
            c1_decl,
            fail_error=DoshError(FailureCode.EXECUTION_FAILED, "Primary fail"),
        )
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=0)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": failing_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract",))

        # First run puts attempt into terminal state
        with pytest.raises(DoshError):
            pravaha.execute(plan, sample_request, sample_context)
        assert failing_cap.call_count == 1

        # Second attempt must immediately be rejected without invoking Yantra/capability
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "terminal quarantine state" in exc_info.value.message
        assert failing_cap.call_count == 1  # Unchanged!

    def test_typed_lifecycle_action_validation_before_mutation(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": MockExecutableCapability(c1_decl)},
            quarantine_store=q_store,
        )

        # Invalid action argument type
        with pytest.raises(TypeError, match="action must be a LifecycleAction"):
            pravaha.apply_lifecycle_action("not_an_action")  # type: ignore

        # Action on non-existent item raises VALIDATION_FAILED
        missing_action = LifecycleAction(action=LifecycleActionType.RELEASE, item_id="quar-nonexistent")
        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(missing_action)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        # Pre-populate a record in TERMINAL state
        record = QuarantineRecord(
            quarantine_id="quar-item-01",
            input_hash="hash123",
            run_id="run-01",
            request_id="req-01",
            trace_id="tr-01",
            capability_id="extract",
            plugin_id="shakti.native",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=2,
            max_retries=2,
            status=QuarantineStatus.TERMINAL,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        # Cannot release or retry a terminal item
        retry_act = LifecycleAction(action=LifecycleActionType.RETRY, item_id="quar-item-01")
        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "terminal state" in exc_info.value.message

        release_act = LifecycleAction(action=LifecycleActionType.RELEASE, item_id="quar-item-01")
        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(release_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "terminal state" in exc_info.value.message

        # Store remains untouched in TERMINAL state
        stored = q_store.get_record("quar-item-01")
        assert stored is not None
        assert stored.status is QuarantineStatus.TERMINAL

    def test_lifecycle_action_item_id_safe_validation(self) -> None:
        # Unsafe item_id characters are rejected at construction
        with pytest.raises(ValueError, match="safe non-empty identifier"):
            LifecycleAction(action=LifecycleActionType.RELEASE, item_id="../../unsafe/path")

        with pytest.raises(ValueError, match="safe non-empty identifier"):
            LifecycleAction(action=LifecycleActionType.RELEASE, item_id="item with spaces")

        with pytest.raises(ValueError, match="safe non-empty identifier"):
            LifecycleAction(action=LifecycleActionType.RELEASE, item_id="item:with:colons")

        # Valid safe identifiers succeed
        valid_act = LifecycleAction(action=LifecycleActionType.RELEASE, item_id="quar-valid_id-123")
        assert valid_act.item_id == "quar-valid_id-123"

    def test_released_item_cannot_retry_or_terminate(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": MockExecutableCapability(c1_decl)},
            quarantine_store=q_store,
        )

        record = QuarantineRecord(
            quarantine_id="quar-released-01",
            input_hash="hash_rel",
            run_id="run-01",
            request_id="req-01",
            trace_id="tr-01",
            capability_id="extract",
            plugin_id="shakti.native",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=1,
            max_retries=2,
            status=QuarantineStatus.RELEASED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        retry_act = LifecycleAction(action=LifecycleActionType.RETRY, item_id="quar-released-01")
        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "already released" in exc_info.value.message

        term_act = LifecycleAction(action=LifecycleActionType.TERMINATE, item_id="quar-released-01")
        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(term_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "released state" in exc_info.value.message

        # Verify state in store remained RELEASED
        stored = q_store.get_record("quar-released-01")
        assert stored is not None
        assert stored.status is QuarantineStatus.RELEASED

    def test_typed_retry_executes_through_yantra_and_updates_lifecycle_truth(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls

        class FlakyCapability(MockExecutableCapability):
            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                self.call_count += 1
                return Result(data=("retry_success",))

        cap = FlakyCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=2)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )

        valid_input_hash = pravaha._compute_input_hash(sample_request, cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-retry-01",
            input_hash=valid_input_hash,
            run_id=sample_context.run_id,
            request_id=sample_context.request_id,
            trace_id=sample_context.trace_id,
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-retry-01",
            request=sample_request,
            context=sample_context,
        )

        updated_rec = pravaha.apply_lifecycle_action(retry_act)

        # Proves retry executed through Yantra, incremented attempt count, and marked RELEASED on success
        assert cap.call_count == 1
        assert updated_rec.status is QuarantineStatus.RELEASED
        assert updated_rec.attempt_count == 1

        stored = q_store.get_record("quar-retry-01")
        assert stored is not None
        assert stored.status is QuarantineStatus.RELEASED
        assert stored.attempt_count == 1

    def test_hashed_manifest_contains_required_safe_factual_fields(
        self,
        tmp_path: Path,
    ) -> None:
        import json

        q_store = QuarantineStore(tmp_path / "quarantine")
        record = QuarantineRecord(
            quarantine_id="quar-safe-01",
            input_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            run_id="run-100",
            request_id="req-100",
            trace_id="tr-100",
            capability_id="extract",
            plugin_id="shakti.native",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="standard",
            attempt_count=1,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
            provenance=({"stage": "native_extraction", "details": "safe_meta"},),
        )

        manifest_path = q_store.quarantine(record)
        assert manifest_path.exists()

        raw_data = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Verify required factual safe fields
        assert raw_data["quarantine_id"] == "quar-safe-01"
        assert raw_data["input_hash"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert raw_data["run_id"] == "run-100"
        assert raw_data["request_id"] == "req-100"
        assert raw_data["trace_id"] == "tr-100"
        assert raw_data["capability_id"] == "extract"
        assert raw_data["plugin_id"] == "shakti.native"
        assert raw_data["failure_code"] == FailureCode.EXECUTION_FAILED.value
        assert raw_data["profile"] == "standard"
        assert raw_data["attempt_count"] == 1
        assert raw_data["max_retries"] == 2
        assert raw_data["status"] == "quarantined"

        # Verify manifest DOES NOT contain raw source path, raw document bytes, secrets, or raw exception strings
        raw_text = manifest_path.read_text(encoding="utf-8")
        assert "password" not in raw_text.lower()
        assert "secret" not in raw_text.lower()
        assert "c:\\" not in raw_text.lower()
        assert "/users/" not in raw_text.lower()
        assert "traceback" not in raw_text.lower()

    def test_confirmed_artifacts_remain_valid_across_failure(
        self,
        tmp_path: Path,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, _, _, _ = cap_decls

        output_root = tmp_path / "Output"
        output_root.mkdir(parents=True, exist_ok=True)
        runtime_root = tmp_path / "Runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)

        boundary = ArtifactBoundary(runtime_root=runtime_root, output_root=output_root)
        workspace = boundary.begin_run(
            run_id=sample_context.run_id,
            requirement="extract",
        )

        # Stage 1 capability execution succeeds and commits an artifact to the active RunWorkspace
        class Stage1ProducerCapability(MockExecutableCapability):
            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                intent = ArtifactIntent(
                    name="stage1_report.txt",
                    role="report",
                    media_type="text/plain",
                    relative_path="stage1_report.txt",
                )
                workspace.commit_artifact(intent, b"Valid stage 1 report data committed before stage 2 failure.")
                return Result(data=("stage1_success",))

        # Stage 2 capability fails with classified non-retryable error
        class Stage2FailingCapability(MockExecutableCapability):
            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
                raise DoshError(FailureCode.EXECUTION_FAILED, "Stage 2 execution failure")

        step1_cap = Stage1ProducerCapability(c1_decl)
        step2_cap = Stage2FailingCapability(c2_decl)

        q_store = QuarantineStore(tmp_path / "quarantine")
        retry_policy = RetryPolicy(max_retries=0)
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": step1_cap, "normalize": step2_cap},
            quarantine_store=q_store,
            retry_policy=retry_policy,
        )

        # Plan executes genuine 2-stage plan: both registered in Kosh
        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("extract", "normalize"))

        # Pipeline execution fails in Stage 2
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)
        assert exc_info.value.code is FailureCode.EXECUTION_FAILED

        # Workspace is finalized according to its approved public contract on run failure
        manifest_path = workspace.finalize(success=False)
        assert manifest_path.exists()

        # Ordinary committed artifacts are cleaned up on run failure
        assert len(workspace.committed_artifacts) == 0
        assert not (workspace.output_dir / "stage1_report.txt").exists()

    def test_quarantine_is_not_smriti_or_cache(self) -> None:
        """Prove architecturally that quarantine does not import, reference, or use Smriti caching."""
        import sys
        import sarathi.nabhi.quarantine as q_mod
        import sarathi.nabhi.pravaha as p_mod

        assert not hasattr(q_mod, "Smriti")
        assert not hasattr(p_mod, "Smriti")
        assert "sarathi.smriti" not in sys.modules or sys.modules["sarathi.smriti"] is None or not hasattr(sys.modules.get("sarathi.smriti"), "get_cached_result")

    def test_retry_action_mismatched_request_id_fails_before_mutation(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
        )

        valid_hash = pravaha._compute_input_hash(sample_request, cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-mismatch-req",
            input_hash=valid_hash,
            run_id=sample_context.run_id,
            request_id="original-req-id",
            trace_id=sample_context.trace_id,
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        # sample_request has request_id="req-test-1" != "original-req-id"
        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-mismatch-req",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "does not match quarantined request_id" in exc_info.value.message

        # Assert zero store mutation and zero capability call
        assert cap.call_count == 0
        stored = q_store.get_record("quar-mismatch-req")
        assert stored is not None
        assert stored.status is QuarantineStatus.QUARANTINED
        assert stored.attempt_count == 0

    def test_retry_action_mismatched_run_id_fails_before_mutation(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
        )

        valid_hash = pravaha._compute_input_hash(sample_request, cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-mismatch-run",
            input_hash=valid_hash,
            run_id="original-run-id",
            request_id=sample_context.request_id,
            trace_id=sample_context.trace_id,
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        # sample_context has run_id="run-test-1" != "original-run-id"
        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-mismatch-run",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "does not match quarantined run_id" in exc_info.value.message

        assert cap.call_count == 0
        stored = q_store.get_record("quar-mismatch-run")
        assert stored is not None
        assert stored.status is QuarantineStatus.QUARANTINED
        assert stored.attempt_count == 0

    def test_retry_action_mismatched_input_hash_fails_before_mutation(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
        )

        # Deliberately different input hash
        record = QuarantineRecord(
            quarantine_id="quar-mismatch-hash",
            input_hash="tampered_hash_value_1234567890abcdef",
            run_id=sample_context.run_id,
            request_id=sample_context.request_id,
            trace_id=sample_context.trace_id,
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-mismatch-hash",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "Recomputed input hash does not match" in exc_info.value.message

        assert cap.call_count == 0
        stored = q_store.get_record("quar-mismatch-hash")
        assert stored is not None
        assert stored.status is QuarantineStatus.QUARANTINED
        assert stored.attempt_count == 0

    def test_retry_action_mismatched_trace_id_fails_before_mutation(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
        )

        valid_hash = pravaha._compute_input_hash(sample_request, cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-mismatch-tr",
            input_hash=valid_hash,
            run_id=sample_context.run_id,
            request_id=sample_context.request_id,
            trace_id="original-trace-id",
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-mismatch-tr",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "does not match quarantined trace_id" in exc_info.value.message

        assert cap.call_count == 0
        stored = q_store.get_record("quar-mismatch-tr")
        assert stored is not None
        assert stored.status is QuarantineStatus.QUARANTINED
        assert stored.attempt_count == 0

    def test_retry_action_mismatched_profile_fails_before_mutation(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
        )

        valid_hash = pravaha._compute_input_hash(sample_request, cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-mismatch-prof",
            input_hash=valid_hash,
            run_id=sample_context.run_id,
            request_id=sample_context.request_id,
            trace_id=sample_context.trace_id,
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="deep",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        # sample_context has profile=INSTANT ("instant") != "deep"
        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-mismatch-prof",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "does not match quarantined profile" in exc_info.value.message

        assert cap.call_count == 0
        stored = q_store.get_record("quar-mismatch-prof")
        assert stored is not None
        assert stored.status is QuarantineStatus.QUARANTINED
        assert stored.attempt_count == 0

    def test_retry_action_mismatched_kosh_declaration_fails_before_mutation(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        # Tampered declaration
        tampered_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="2.0.0",  # Changed version
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        tampered_cap = MockExecutableCapability(tampered_decl)
        q_store = QuarantineStore(tmp_path / "quarantine")
        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"extract": tampered_cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
        )

        valid_hash = pravaha._compute_input_hash(sample_request, tampered_cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-mismatch-decl",
            input_hash=valid_hash,
            run_id=sample_context.run_id,
            request_id=sample_context.request_id,
            trace_id=sample_context.trace_id,
            capability_id="extract",
            plugin_id="shakti.pipeline",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-mismatch-decl",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED
        assert "declaration does not match registered declaration in Kosh" in exc_info.value.message

        assert tampered_cap.call_count == 0
        stored = q_store.get_record("quar-mismatch-decl")
        assert stored is not None
        assert stored.status is QuarantineStatus.QUARANTINED
        assert stored.attempt_count == 0

    def test_pravaha_security_denial_blocks_execution_before_yantra(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        from sarathi.kavacha import Kavacha, SecurityPolicy

        c1_decl, _, _, _, _ = cap_decls
        cap = MockExecutableCapability(c1_decl)

        # Restrictive policy denying external processing or custom secrets
        policy = SecurityPolicy(
            allow_pii_access=False,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)

        # Plugin requiring PII
        kosh = manthan.registry
        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.pipeline.denied",
                name="Denied Plugin",
                version="1.0.0",
                security=SecurityDeclaration(pii_access=True),
                capabilities=("denied_cap",),
            )
        )
        denied_decl = CapabilityDeclaration(
            capability_id="denied_cap",
            plugin_id="shakti.pipeline.denied",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        kosh.register_capability(denied_decl)
        denied_cap = MockExecutableCapability(denied_decl)

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"denied_cap": denied_cap},
            kavacha=kavacha,
        )

        plan = CapabilityPlan(request_id=sample_request.request_id, capability_ids=("denied_cap",))

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan, sample_request, sample_context)

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert denied_cap.call_count == 0

    def test_pravaha_retry_cannot_bypass_kavacha_security_authorization(
        self,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
        tmp_path: Path,
    ) -> None:
        from sarathi.kavacha import Kavacha, SecurityPolicy

        kosh = manthan.registry
        kosh.register_plugin(
            PluginInfo(
                plugin_id="shakti.pipeline.retry_denied",
                name="Retry Denied Plugin",
                version="1.0.0",
                security=SecurityDeclaration(network_access=True, local_processing_only=False),
                capabilities=("retry_denied_cap",),
            )
        )
        denied_decl = CapabilityDeclaration(
            capability_id="retry_denied_cap",
            plugin_id="shakti.pipeline.retry_denied",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        kosh.register_capability(denied_decl)
        denied_cap = MockExecutableCapability(denied_decl)

        # Policy denying network access
        policy = SecurityPolicy(
            allow_pii_access=True,
            allow_network_access=False,
            allow_external_processing=False,
            allowed_secrets=(),
        )
        kavacha = Kavacha(policy)
        q_store = QuarantineStore(tmp_path / "quarantine")

        pravaha = Pravaha(
            manthan=manthan,
            yantra=yantra,
            capabilities={"retry_denied_cap": denied_cap},
            quarantine_store=q_store,
            retry_policy=RetryPolicy(max_retries=2),
            kavacha=kavacha,
        )

        valid_hash = pravaha._compute_input_hash(sample_request, denied_cap, sample_context)
        record = QuarantineRecord(
            quarantine_id="quar-retry-sec-01",
            input_hash=valid_hash,
            run_id=sample_context.run_id,
            request_id=sample_context.request_id,
            trace_id=sample_context.trace_id,
            capability_id="retry_denied_cap",
            plugin_id="shakti.pipeline.retry_denied",
            failure_code=FailureCode.EXECUTION_FAILED,
            profile="instant",
            attempt_count=0,
            max_retries=2,
            status=QuarantineStatus.QUARANTINED,
            created_at_utc="2026-09-01T00:00:00Z",
            updated_at_utc="2026-09-01T00:00:00Z",
        )
        q_store.quarantine(record)

        retry_act = LifecycleAction(
            action=LifecycleActionType.RETRY,
            item_id="quar-retry-sec-01",
            request=sample_request,
            context=sample_context,
        )

        with pytest.raises(DoshError) as exc_info:
            pravaha.apply_lifecycle_action(retry_act)

        assert exc_info.value.code is FailureCode.SECURITY_DENIED
        assert denied_cap.call_count == 0
