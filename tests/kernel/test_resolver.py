"""Unit tests for Nabhi — Core Kernel: Manthan Capability Resolver."""

from pathlib import Path
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh
from sarathi.nabhi.manthan import CapabilityPlan, Manthan
from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    InputRef,
    PluginInfo,
    Request,
    SecurityDeclaration,
)


@pytest.fixture
def sample_plugin() -> PluginInfo:
    return PluginInfo(
        plugin_id="shakti.ocr",
        name="OCR Plugin",
        version="2.0.0",
        security=SecurityDeclaration(),
        capabilities=("ocr",),
    )


@pytest.fixture
def sample_capability() -> CapabilityDeclaration:
    return CapabilityDeclaration(
        capability_id="ocr",
        plugin_id="shakti.ocr",
        version="2.0.0",
        supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
        supported_input_types=("application/pdf", "image/png"),
    )


@pytest.fixture
def sample_request() -> Request:
    return Request(
        request_id="req-123",
        requirement="ocr",
        inputs=(
            InputRef(
                input_id="inp-1",
                source_path=Path("doc.pdf"),
                display_name="Document",
                size_bytes=1024,
                media_type="application/pdf",
            ),
        ),
        profile=ExecutionProfile.INSTANT,
    )


@pytest.fixture
def kosh(sample_plugin: PluginInfo, sample_capability: CapabilityDeclaration) -> Kosh:
    registry = Kosh()
    registry.register_plugin(sample_plugin)
    registry.register_capability(sample_capability)
    return registry


class TestCapabilityPlanContract:
    def test_valid_plan_creation(self) -> None:
        plan = CapabilityPlan(request_id="req-1", capability_ids=("ocr",))
        assert plan.request_id == "req-1"
        assert plan.capability_ids == ("ocr",)
        assert isinstance(plan.capability_ids, tuple)

    def test_plan_immutability(self) -> None:
        plan = CapabilityPlan(request_id="req-1", capability_ids=("ocr",))
        with pytest.raises(Exception):
            plan.request_id = "req-2"  # type: ignore
        with pytest.raises(Exception):
            plan.capability_ids = ("other",)  # type: ignore

    def test_invalid_plan_arguments(self) -> None:
        with pytest.raises(ValueError, match="request_id must be a non-empty string"):
            CapabilityPlan(request_id="   ", capability_ids=("ocr",))

        with pytest.raises(TypeError, match="capability_ids must be an ordered sequence"):
            CapabilityPlan(request_id="req-1", capability_ids={"ocr"})  # type: ignore

        with pytest.raises(ValueError, match="capability_ids cannot be empty"):
            CapabilityPlan(request_id="req-1", capability_ids=())

        with pytest.raises(ValueError, match="capability_ids\\[0\\] must be a non-empty string"):
            CapabilityPlan(request_id="req-1", capability_ids=("",))


class TestManthanResolver:
    def test_exact_successful_resolution(self, kosh: Kosh, sample_request: Request) -> None:
        manthan = Manthan(kosh)
        plan = manthan.resolve(sample_request)

        assert isinstance(plan, CapabilityPlan)
        assert plan.request_id == "req-123"
        assert plan.capability_ids == ("ocr",)

    def test_resolve_passing_registry_explicitly(
        self, kosh: Kosh, sample_request: Request
    ) -> None:
        manthan = Manthan()
        plan = manthan.resolve(sample_request, registry=kosh)

        assert plan.request_id == "req-123"
        assert plan.capability_ids == ("ocr",)

    def test_unsupported_requirement_rejected(self, kosh: Kosh) -> None:
        request = Request(
            request_id="req-unknown",
            requirement="unknown_requirement",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("file.txt"),
                    display_name="File",
                    size_bytes=100,
                    media_type="text/plain",
                ),
            ),
        )
        manthan = Manthan(kosh)

        with pytest.raises(DoshError) as exc_info:
            manthan.resolve(request)

        err = exc_info.value
        assert err.code is FailureCode.UNSUPPORTED
        assert "No capability registered for requirement 'unknown_requirement'" in err.message

    def test_unsupported_execution_profile_rejected(
        self, kosh: Kosh, sample_request: Request
    ) -> None:
        # Request a profile not supported by "ocr" (which supports INSTANT, ACCURATE)
        req_profile = Request(
            request_id="req-profile",
            requirement="ocr",
            inputs=sample_request.inputs,
            profile=ExecutionProfile.LAYOUT_PRESERVING,
        )
        manthan = Manthan(kosh)

        with pytest.raises(DoshError) as exc_info:
            manthan.resolve(req_profile)

        err = exc_info.value
        assert err.code is FailureCode.UNSUPPORTED
        assert "does not support requested execution profile 'layout_preserving'" in err.message

    def test_declared_input_type_mismatch_rejected(self, kosh: Kosh) -> None:
        # Capability supports ("application/pdf", "image/png"); request provides "text/plain"
        req_mismatch = Request(
            request_id="req-mismatch",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("file.txt"),
                    display_name="File",
                    size_bytes=100,
                    media_type="text/plain",
                ),
            ),
        )
        manthan = Manthan(kosh)

        with pytest.raises(DoshError) as exc_info:
            manthan.resolve(req_mismatch)

        err = exc_info.value
        assert err.code is FailureCode.UNSUPPORTED
        assert "Input 'inp-1' media type 'text/plain' is not supported" in err.message

    def test_missing_media_type_rejected_when_capability_declares_supported_inputs(
        self, kosh: Kosh
    ) -> None:
        req_no_media = Request(
            request_id="req-no-media",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="Doc",
                    size_bytes=500,
                    media_type=None,
                ),
            ),
        )
        manthan = Manthan(kosh)

        with pytest.raises(DoshError) as exc_info:
            manthan.resolve(req_no_media)

        err = exc_info.value
        assert err.code is FailureCode.UNSUPPORTED
        assert "Input 'inp-1' is missing media_type" in err.message

    def test_capability_with_no_input_types_allows_any_media_type(self) -> None:
        registry = Kosh()
        plugin = PluginInfo(
            plugin_id="generic.plugin",
            name="Generic Plugin",
            version="1.0.0",
            capabilities=("generic",),
        )
        cap = CapabilityDeclaration(
            capability_id="generic",
            plugin_id="generic.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            supported_input_types=(),  # No declared input types
        )
        registry.register_plugin(plugin)
        registry.register_capability(cap)

        req = Request(
            request_id="req-any",
            requirement="generic",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("file.xyz"),
                    display_name="Custom",
                    size_bytes=50,
                    media_type=None,
                ),
            ),
        )
        manthan = Manthan(registry)
        plan = manthan.resolve(req)
        assert plan.capability_ids == ("generic",)

    def test_invalid_public_arguments_reject_before_registry_access(self, kosh: Kosh) -> None:
        manthan = Manthan()

        with pytest.raises(TypeError, match="request must be a Request instance"):
            manthan.resolve("not_a_request", registry=kosh)  # type: ignore

        with pytest.raises(TypeError, match="registry must be a Kosh instance"):
            manthan.resolve(
                Request(
                    request_id="req-1",
                    requirement="ocr",
                    inputs=(
                        InputRef(
                            input_id="inp-1",
                            source_path=Path("a.pdf"),
                            display_name="A",
                            size_bytes=10,
                        ),
                    ),
                ),
                registry="not_a_kosh",  # type: ignore
            )

        with pytest.raises(TypeError, match="registry must be a Kosh instance"):
            Manthan(registry="bad_registry")  # type: ignore

    def test_media_type_case_insensitive(self, kosh: Kosh) -> None:
        req_upper = Request(
            request_id="req-upper",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="Doc",
                    size_bytes=500,
                    media_type="APPLICATION/PDF",
                ),
            ),
        )
        manthan = Manthan(kosh)
        plan = manthan.resolve(req_upper)
        assert plan.capability_ids == ("ocr",)

    def test_multiple_inputs_all_must_match(self, kosh: Kosh) -> None:
        req_multi = Request(
            request_id="req-multi",
            requirement="ocr",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc1.pdf"),
                    display_name="Doc 1",
                    size_bytes=500,
                    media_type="application/pdf",
                ),
                InputRef(
                    input_id="inp-2",
                    source_path=Path("doc2.png"),
                    display_name="Doc 2",
                    size_bytes=300,
                    media_type="image/png",
                ),
            ),
        )
        manthan = Manthan(kosh)
        plan = manthan.resolve(req_multi)
        assert plan.capability_ids == ("ocr",)

    def test_manthan_does_not_mutate_kosh(
        self, kosh: Kosh, sample_request: Request
    ) -> None:
        # Record baseline state of Kosh
        plugins_before = kosh.plugins()
        caps_before = kosh.capabilities()
        count_before = len(kosh)

        manthan = Manthan(kosh)
        plan = manthan.resolve(sample_request)

        assert plan.capability_ids == ("ocr",)
        # Verify Kosh remains completely unchanged
        assert len(kosh) == count_before
        assert kosh.plugins() == plugins_before
        assert kosh.capabilities() == caps_before
