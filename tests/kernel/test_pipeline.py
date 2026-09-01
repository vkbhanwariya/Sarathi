"""Unit tests for Nabhi — Core Kernel: Pravaha Dynamic Pipeline Engine."""

from pathlib import Path
from typing import Any
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import CapabilityPlan, Kosh, Pravaha
from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
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
    ) -> None:
        self.declaration = declaration
        self.fail_error = fail_error
        self.transform_data_fn = transform_data_fn
        self.append_warning = append_warning
        self.append_provenance = append_provenance
        self.tracker = tracker
        self.return_invalid_type = return_invalid_type
        self.call_count = 0
        self.received_prior_results: list[Result | None] = []

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.call_count += 1
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
        )


@pytest.fixture
def sample_plugin() -> PluginInfo:
    return PluginInfo(
        plugin_id="shakti.pipeline",
        name="Pipeline Plugin",
        version="1.0.0",
        security=SecurityDeclaration(),
        capabilities=("extract", "normalize", "export"),
    )


@pytest.fixture
def cap_decls(sample_plugin: PluginInfo) -> tuple[CapabilityDeclaration, CapabilityDeclaration, CapabilityDeclaration]:
    c1 = CapabilityDeclaration(
        capability_id="extract",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT,),
    )
    c2 = CapabilityDeclaration(
        capability_id="normalize",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT,),
    )
    c3 = CapabilityDeclaration(
        capability_id="export",
        plugin_id="shakti.pipeline",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT,),
    )
    return (c1, c2, c3)


@pytest.fixture
def kosh(sample_plugin: PluginInfo, cap_decls: tuple[CapabilityDeclaration, ...]) -> Kosh:
    registry = Kosh()
    registry.register_plugin(sample_plugin)
    for c in cap_decls:
        registry.register_capability(c)
    return registry


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
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, c3_decl = cap_decls
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

        pravaha = Pravaha(kosh)
        final_result = pravaha.execute(
            plan=plan,
            request=sample_request,
            context=sample_context,
            capabilities=capabilities,
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

    def test_missing_executable_binding_rejects_before_execution(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)

        # Plan requires 'extract' and 'normalize', but capabilities only provides 'extract'
        capabilities = {"extract": cap1}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "normalize"))

        pravaha = Pravaha(kosh)
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
            )

        err = exc_info.value
        assert err.code is FailureCode.DEPENDENCY_UNAVAILABLE
        assert "Executable capability 'normalize' is not provided" in err.message

        # Assert no stage was executed before validation failure
        assert cap1.call_count == 0

    def test_invalid_executable_contract_rejects_before_execution(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)

        class BadCapability:
            pass  # Does not implement Capability protocol

        capabilities = {"extract": cap1, "normalize": BadCapability()}  # type: ignore
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "normalize"))

        pravaha = Pravaha(kosh)
        with pytest.raises(TypeError, match="does not implement Capability protocol"):
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
            )

        # Pre-execution check prevents cap1 from running
        assert cap1.call_count == 0

    def test_declaration_mismatch_with_kosh_rejects_before_execution(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _ = cap_decls

        # Fake capability claiming a different version than what is in Kosh
        tampered_decl = CapabilityDeclaration(
            capability_id="extract",
            plugin_id="shakti.pipeline",
            version="2.0.0",  # Mismatch: Kosh has 1.0.0
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        tampered_cap = MockExecutableCapability(tampered_decl)

        capabilities = {"extract": tampered_cap}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))

        pravaha = Pravaha(kosh)
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
            )

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "declaration does not match registered declaration in Kosh" in err.message
        assert tampered_cap.call_count == 0

    def test_unregistered_capability_in_plan_rejects_before_execution(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _ = cap_decls
        cap1 = MockExecutableCapability(c1_decl)

        capabilities = {"extract": cap1, "ghost_cap": cap1}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract", "ghost_cap"))

        pravaha = Pravaha(kosh)
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
            )

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "Planned capability 'ghost_cap' is not registered in Kosh" in err.message
        assert cap1.call_count == 0

    def test_capability_failure_stops_pipeline_and_preserves_error(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, c2_decl, c3_decl = cap_decls
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

        pravaha = Pravaha(kosh)
        with pytest.raises(RuntimeError) as exc_info:
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
            )

        # Original exception is preserved unchanged
        assert exc_info.value is original_error

        # cap1 ran, cap2 failed, cap3 was never executed
        assert events == ["extract", "normalize"]
        assert cap1.call_count == 1
        assert cap2.call_count == 1
        assert cap3.call_count == 0

    def test_invalid_plan_request_or_context_rejects(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        pravaha = Pravaha(kosh)
        c1_decl, _, _ = cap_decls
        capabilities = {"extract": MockExecutableCapability(c1_decl)}

        # Mismatched request_id between plan and request
        bad_plan = CapabilityPlan(request_id="mismatched-req", capability_ids=("extract",))
        with pytest.raises(DoshError) as exc_info:
            pravaha.execute(
                plan=bad_plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
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
                capabilities=capabilities,
            )
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        # Invalid argument types
        with pytest.raises(TypeError, match="plan must be a CapabilityPlan"):
            pravaha.execute(plan="not_a_plan", request=sample_request, context=sample_context, capabilities=capabilities)  # type: ignore

        with pytest.raises(TypeError, match="request must be a Request"):
            pravaha.execute(plan=plan, request="not_a_request", context=sample_context, capabilities=capabilities)  # type: ignore

        with pytest.raises(TypeError, match="context must be an ExecutionContext"):
            pravaha.execute(plan=plan, request=sample_request, context="not_a_context", capabilities=capabilities)  # type: ignore

        with pytest.raises(TypeError, match="capabilities must be a Mapping"):
            pravaha.execute(plan=plan, request=sample_request, context=sample_context, capabilities=["not_a_map"])  # type: ignore

        with pytest.raises(TypeError, match="registry must be a Kosh instance"):
            Pravaha(registry="bad_registry")  # type: ignore

    def test_capability_returning_non_result_rejects(
        self,
        kosh: Kosh,
        cap_decls: tuple[CapabilityDeclaration, ...],
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        c1_decl, _, _ = cap_decls
        bad_return_cap = MockExecutableCapability(c1_decl, return_invalid_type={"raw": "dict_instead_of_result"})

        capabilities = {"extract": bad_return_cap}
        plan = CapabilityPlan(request_id="req-pipe-1", capability_ids=("extract",))

        pravaha = Pravaha(kosh)
        with pytest.raises(TypeError, match="must return a Result instance"):
            pravaha.execute(
                plan=plan,
                request=sample_request,
                context=sample_context,
                capabilities=capabilities,
            )
