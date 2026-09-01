"""Unit tests for Nabhi — Core Kernel: Pravaha Dynamic Pipeline Engine."""

from pathlib import Path
from typing import Any
from unittest.mock import patch
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import CapabilityPlan, Kosh, Manthan, Pravaha
from sarathi.sankalpa import (
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
        c1_decl, c2_decl, c3_decl, _, _ = cap_decls
        events: list[str] = []

        warn1 = WarningRecord(code="W001", message="Warning stage 1", stage="extract")
        prov1 = ProvenanceRecord(stage="extract", plugin_id="shakti.pipeline", capability_id="extract")

        warn2 = WarningRecord(code="W002", message="Warning stage 2", stage="normalize")
        prov2 = ProvenanceRecord(stage="normalize", plugin_id="shakti.pipeline", capability_id="normalize")

        warn3 = WarningRecord(code="W003", message="Warning stage 3", stage="export")
        prov3 = ProvenanceRecord(stage="export", plugin_id="shakti.pipeline", capability_id="export")

        cap1 = MockExecutableCapability(c1_decl, append_warning=warn1, append_provenance=prov1, tracker=events)
        cap2 = MockExecutableCapability(c2_decl, append_warning=warn2, append_provenance=prov2, tracker=events)
        cap3 = MockExecutableCapability(c3_decl, append_warning=warn3, append_provenance=prov3, tracker=events)

        capabilities = {
            "extract": cap1,
            "normalize": cap2,
            "export": cap3,
        }

        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "normalize", "export"))

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        final_result = pravaha.execute(
            plan=plan,
            request=sample_request,
            context=sample_context,
        )

        assert events == ["extract", "normalize", "export"]
        assert cap1.call_count == 1
        assert cap2.call_count == 1
        assert cap3.call_count == 1

        # Stage 1 received prior_result=None
        assert cap1.received_prior_results[0] is None

        # Stage 2 received Stage 1's Result
        stage1_res = cap2.received_prior_results[0]
        assert isinstance(stage1_res, Result)
        assert stage1_res.data == "extract"

        # Stage 3 received Stage 2's Result
        stage2_res = cap3.received_prior_results[0]
        assert isinstance(stage2_res, Result)
        assert stage2_res.data == "extract+normalize"

        # Final result contains concatenated data and accumulated warnings/provenance
        assert isinstance(final_result, Result)
        assert final_result.data == "extract+normalize+export"
        assert final_result.warnings == (warn1, warn2, warn3)
        assert final_result.provenance == (prov1, prov2, prov3)
        assert final_result.next_requirement is None

    def test_pravaha_invokes_capabilities_strictly_through_yantra(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)
        capabilities = {"extract": cap1}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))

        yantra_execute_calls: list[str] = []
        original_yantra_execute = yantra.execute

        def spy_execute(capability: Any, request: Any, context: Any, prior_result: Any = None) -> Result:
            yantra_execute_calls.append(capability.declaration.capability_id)
            return original_yantra_execute(capability, request, context, prior_result)

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)

        with patch.object(yantra, "execute", side_effect=spy_execute):
            result = pravaha.execute(plan=plan, request=sample_request, context=sample_context)

        assert result.data == "extract"
        assert yantra_execute_calls == ["extract"]
        assert cap1.call_count == 1

    def test_next_requirement_handoff_from_native_extraction_to_ocr(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_context: ExecutionContext,
    ) -> None:
        _, _, _, ocr_decl, read_decl = cap_decls
        events: list[str] = []

        warn_native = WarningRecord(code="PARTIAL_NATIVE", message="Scan page detected", stage="read_native")
        prov_native = ProvenanceRecord(stage="read_native", plugin_id="shakti.pipeline", capability_id="read_native")

        # Native extractor discovers image/scan content and signals OCR requirement
        read_native_cap = MockExecutableCapability(
            read_decl,
            append_warning=warn_native,
            append_provenance=prov_native,
            tracker=events,
            next_requirement="ocr",
        )

        warn_ocr = WarningRecord(code="OCR_PASS", message="OCR completed", stage="ocr")
        prov_ocr = ProvenanceRecord(stage="ocr", plugin_id="shakti.pipeline", capability_id="ocr")

        ocr_cap = MockExecutableCapability(
            ocr_decl,
            append_warning=warn_ocr,
            append_provenance=prov_ocr,
            tracker=events,
            next_requirement=None,
        )

        capabilities = {
            "read_native": read_native_cap,
            "ocr": ocr_cap,
        }

        initial_request = Request(
            request_id="req-scan-1",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-scan",
                    source_path=Path("mixed_doc.pdf"),
                    display_name="mixed_doc.pdf",
                    size_bytes=4096,
                ),
            ),
        )

        initial_plan = manthan.resolve(initial_request)
        assert initial_plan.capability_ids == ("read_native",)

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        context = ExecutionContext(run_id="run-1", request_id="req-scan-1", trace_id="tr-1", span_id="sp-1")

        final_result = pravaha.execute(plan=initial_plan, request=initial_request, context=context)

        # Proves ordered sequencing: read_native executed first, then escalated to ocr
        assert events == ["read_native", "ocr"]
        assert read_native_cap.call_count == 1
        assert ocr_cap.call_count == 1

        # Proves OCR capability received Shruti's Result as prior_result
        ocr_prior = ocr_cap.received_prior_results[0]
        assert isinstance(ocr_prior, Result)
        assert ocr_prior.data == "read_native"
        assert ocr_prior.warnings == (warn_native,)
        assert ocr_prior.provenance == (prov_native,)

        # Proves final result accumulates both stages
        assert final_result.data == "read_native+ocr"
        assert final_result.warnings == (warn_native, warn_ocr)
        assert final_result.provenance == (prov_native, prov_ocr)
        assert final_result.next_requirement is None

    def test_next_requirement_preserves_request_fields(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
    ) -> None:
        _, _, _, ocr_decl, read_decl = cap_decls

        read_cap = MockExecutableCapability(read_decl, next_requirement="ocr")
        ocr_cap = MockExecutableCapability(ocr_decl)
        capabilities = {"read_native": read_cap, "ocr": ocr_cap}

        custom_opts = {"ocr_engine": "rapidocr", "dpi": 300}
        custom_meta = {"department": "finance", "user": "auditor"}
        initial_request = Request(
            request_id="req-handoff-fields",
            requirement="read_native",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("input.pdf"),
                    display_name="input.pdf",
                    size_bytes=1000,
                ),
            ),
            profile=ExecutionProfile.ACCURATE,
            custom_options=custom_opts,
            output_root=Path("out/handoff"),
            preserve_partial=True,
            metadata=custom_meta,
        )

        plan = manthan.resolve(initial_request)
        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        context = ExecutionContext(run_id="run-1", request_id="req-handoff-fields", trace_id="tr-1", span_id="sp-1")

        pravaha.execute(plan=plan, request=initial_request, context=context)

        # Verify OCR received identical request fields except for requirement
        ocr_req = ocr_cap.received_requests[0]
        assert ocr_req.request_id == "req-handoff-fields"
        assert ocr_req.requirement == "ocr"
        assert ocr_req.inputs == initial_request.inputs
        assert ocr_req.profile == ExecutionProfile.ACCURATE
        assert ocr_req.custom_options == custom_opts
        assert ocr_req.output_root == Path("out/handoff")
        assert ocr_req.preserve_partial is True
        assert ocr_req.metadata == custom_meta

    def test_repeated_requirement_handoff_rejected_before_repeat_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls

        # Capability returns next_requirement matching its own initial requirement
        loop_cap = MockExecutableCapability(c1_decl, next_requirement="extract")
        capabilities = {"extract": loop_cap}

        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))
        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan=plan, request=sample_request, context=sample_context)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Repeated requirement 'extract'" in err.message

        # Assert capability was executed only once, repeat was blocked
        assert loop_cap.call_count == 1

    def test_circular_requirement_handoff_rejected(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, _, _, _ = cap_decls

        # 'extract' handoffs to 'normalize', and 'normalize' handoffs back to 'extract'
        cap_extract = MockExecutableCapability(c1_decl, next_requirement="normalize")
        cap_normalize = MockExecutableCapability(c2_decl, next_requirement="extract")

        capabilities = {
            "extract": cap_extract,
            "normalize": cap_normalize,
        }

        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))
        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)

        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(plan=plan, request=sample_request, context=sample_context)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Repeated requirement 'extract'" in err.message

        # Proves extract ran once, normalize ran once, repeat extract was blocked before invocation
        assert cap_extract.call_count == 1
        assert cap_normalize.call_count == 1

    def test_missing_executable_binding_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)

        # Plan requires 'extract' and 'normalize', but capabilities only provides 'extract'
        capabilities = {"extract": cap1}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "normalize"))

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
            )

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Executable capability 'normalize' is not provided" in err.message

        # Assert no stage was executed before validation failure
        assert cap1.call_count == 0

    def test_invalid_executable_contract_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)

        class BadCapability:
            pass  # Does not implement Capability protocol

        capabilities = {"extract": cap1, "normalize": BadCapability()}  # type: ignore
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "normalize"))

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        with pytest.raises(TypeError, match="does not implement Capability protocol"):
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
            )

        # Pre-execution check prevents cap1 from running
        assert cap1.call_count == 0

    def test_declaration_mismatch_with_kosh_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        tampered_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="2.0.0",  # Mismatch: Kosh has 1.0.0
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        tampered_cap = MockExecutableCapability(tampered_decl)

        capabilities = {"extract": tampered_cap}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
            )

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "declaration does not match registered declaration in Kosh" in err.message
        assert tampered_cap.call_count == 0

    def test_unregistered_capability_in_plan_rejects_before_execution(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)

        capabilities = {"extract": cap1, "ghost_cap": cap1}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "ghost_cap"))

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
            )

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Planned capability 'ghost_cap' is not registered in Kosh" in err.message
        assert cap1.call_count == 0

    def test_capability_failure_stops_pipeline_and_preserves_error(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, c3_decl, _, _ = cap_decls
        events: list[str] = []
        original_error = RuntimeError("OCR engine crashed on page 2")

        cap1 = MockExecutableCapability(c1_decl, tracker=events)
        cap2 = MockExecutableCapability(c2_decl, fail_error=original_error, tracker=events)
        cap3 = MockExecutableCapability(c3_decl, tracker=events)

        capabilities = {
            "extract": cap1,
            "normalize": cap2,
            "export": cap3,
        }

        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "normalize", "export"))

        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)
        with pytest.raises(RuntimeError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
            )

        # Original exception is preserved unchanged
        assert exc_info.value is original_error

        # cap1 ran, cap2 failed, cap3 was never executed
        assert events == ["extract", "normalize"]
        assert cap1.call_count == 1
        assert cap2.call_count == 1
        assert cap3.call_count == 0

        # Allocation in Yantra was cleanly released despite the failure
        alloc = yantra.allocate(c1_decl.device_requirement)
        yantra.release(alloc)

    def test_invalid_plan_request_or_context_rejects(
        self,
        kosh: Kosh,
        manthan: Manthan,
        yantra: Yantra,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _, _, _ = cap_decls
        capabilities = {"extract": MockExecutableCapability(c1_decl)}
        pravaha = Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=capabilities)

        # Mismatched request_id between plan and request
        bad_plan = CapabilityPlan(request_id="mismatched-req", capability_ids=("extract",))
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=bad_plan,
                request=sample_request,
                context=sample_context,
            )
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        # Mismatched context request_id
        bad_context = ExecutionContext(
            run_id="run-1",
            request_id="mismatched-ctx-req",
            trace_id="tr-1",
            span_id="sp-1",
        )
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=bad_context,
            )
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        # Invalid argument types to execute()
        with pytest.raises(TypeError, match="plan must be a CapabilityPlan"):
            pravaha.execute(plan="not_a_plan", request=sample_request, context=sample_context)  # type: ignore

        with pytest.raises(TypeError, match="request must be a Request"):
            pravaha.execute(plan=plan, request="not_a_request", context=sample_context)  # type: ignore

        with pytest.raises(TypeError, match="context must be an ExecutionContext"):
            pravaha.execute(plan=plan, request=sample_request, context="not_a_context")  # type: ignore

        # Invalid constructor arguments
        with pytest.raises(TypeError, match="registry must be a Kosh instance"):
            Pravaha(registry="bad_registry", manthan=manthan, yantra=yantra, capabilities=capabilities)  # type: ignore

        with pytest.raises(TypeError, match="manthan must be a Manthan instance"):
            Pravaha(registry=kosh, manthan="bad_manthan", yantra=yantra, capabilities=capabilities)  # type: ignore

        with pytest.raises(TypeError, match="yantra must be a Yantra instance"):
            Pravaha(registry=kosh, manthan=manthan, yantra="bad_yantra", capabilities=capabilities)  # type: ignore

        with pytest.raises(TypeError, match="capabilities must be a Mapping"):
            Pravaha(registry=kosh, manthan=manthan, yantra=yantra, capabilities=["not_a_map"])  # type: ignore
