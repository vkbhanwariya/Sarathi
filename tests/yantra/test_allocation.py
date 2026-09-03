from pathlib import Path
from typing import Any

import pytest

import sarathi.yantra as yantra_module
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.yantra import (
    Allocation,
    DeviceInfo,
    DeviceInventory,
    Yantra,
)


class TestDeviceInfoAndInventory:
    def test_device_info_valid_and_immutable(self) -> None:
        dev = DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=8)
        assert dev.device_id == "cpu-0"
        assert dev.device_type == DeviceType.CPU
        assert dev.capacity == 8

        with pytest.raises(AttributeError):
            dev.capacity = 16  # type: ignore

    def test_device_info_validation_failures(self) -> None:
        with pytest.raises(ValueError, match="device_id must be a non-empty string"):
            DeviceInfo(device_id="", device_type=DeviceType.CPU, capacity=1)

        with pytest.raises(TypeError, match="device_type must be a DeviceType"):
            DeviceInfo(device_id="dev-1", device_type="cpu", capacity=1)  # type: ignore

        with pytest.raises(TypeError, match="capacity must be an integer"):
            DeviceInfo(device_id="dev-1", device_type=DeviceType.CPU, capacity=True)  # type: ignore

        with pytest.raises(ValueError, match="capacity must be a positive integer"):
            DeviceInfo(device_id="dev-1", device_type=DeviceType.CPU, capacity=0)

        with pytest.raises(ValueError, match="capacity must be a positive integer"):
            DeviceInfo(device_id="dev-1", device_type=DeviceType.CPU, capacity=-2)

    def test_device_inventory_construction_and_immutability(self) -> None:
        d1 = DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=2)
        d2 = DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4)
        inv = DeviceInventory([d1, d2])

        assert len(inv) == 2
        assert inv.devices == (d1, d2)
        assert inv.get_device("gpu-0") == d1
        assert inv.get_device("non-existent") is None

        # Immutability
        with pytest.raises(AttributeError):
            inv.devices = ()  # type: ignore

    def test_device_inventory_rejection_of_sets_and_duplicates(self) -> None:
        d1 = DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=1)
        d1_dup = DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=2)

        # Reject sets
        with pytest.raises(TypeError, match="ordered sequence"):
            DeviceInventory({d1})  # type: ignore

        # Reject duplicate device_id
        with pytest.raises(ValueError, match="Duplicate device_id"):
            DeviceInventory([d1, d1_dup])

        # Reject non-DeviceInfo items
        with pytest.raises(TypeError, match="must be a DeviceInfo instance"):
            DeviceInventory(["not_a_device_info"])  # type: ignore


class TestResourceAllocation:
    @pytest.fixture
    def inventory(self) -> DeviceInventory:
        return DeviceInventory(
            [
                DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=1),
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2),
            ]
        )

    def test_preferred_device_allocated_first(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        req = DeviceRequirement(
            preferred_devices=(DeviceType.GPU,),
            supported_devices=(DeviceType.GPU, DeviceType.CPU),
        )

        alloc = yantra.allocate(req)
        assert alloc.device_id == "gpu-0"
        assert alloc.device_type == DeviceType.GPU
        assert alloc.is_spillover is False

    def test_supported_device_spillover_when_preferred_exhausted(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        req = DeviceRequirement(
            preferred_devices=(DeviceType.GPU,),
            supported_devices=(DeviceType.GPU, DeviceType.CPU),
        )

        # First allocation takes the 1 available GPU slot
        alloc1 = yantra.allocate(req)
        assert alloc1.device_id == "gpu-0"
        assert alloc1.is_spillover is False

        # Second allocation spills over to CPU
        alloc2 = yantra.allocate(req)
        assert alloc2.device_id == "cpu-0"
        assert alloc2.device_type == DeviceType.CPU
        assert alloc2.is_spillover is True

    def test_capacity_exhaustion_raises_resource_unavailable(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        req = DeviceRequirement(
            preferred_devices=(DeviceType.GPU,),
            supported_devices=(DeviceType.GPU, DeviceType.CPU),
        )

        # 1 GPU + 2 CPU = 3 slots total
        yantra.allocate(req)  # GPU slot 1/1
        yantra.allocate(req)  # CPU slot 1/2
        yantra.allocate(req)  # CPU slot 2/2

        # 4th allocation should fail with RESOURCE_UNAVAILABLE
        with pytest.raises(DoshError) as exc_info:
            yantra.allocate(req)

        err = exc_info.value
        assert err.code is FailureCode.RESOURCE_UNAVAILABLE
        assert "No compatible device capacity" in err.message

    def test_unsupported_device_type_raises_resource_unavailable(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        npu_req = DeviceRequirement(
            preferred_devices=(DeviceType.NPU,),
            supported_devices=(DeviceType.NPU,),
        )

        with pytest.raises(DoshError) as exc_info:
            yantra.allocate(npu_req)

        err = exc_info.value
        assert err.code is FailureCode.RESOURCE_UNAVAILABLE

    def test_release_restores_capacity(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        req = DeviceRequirement(
            preferred_devices=(DeviceType.GPU,),
            supported_devices=(DeviceType.GPU, DeviceType.CPU),
        )

        # Take GPU
        alloc_gpu = yantra.allocate(req)
        assert alloc_gpu.device_id == "gpu-0"
        assert alloc_gpu.is_spillover is False

        # Release GPU
        yantra.release(alloc_gpu)

        # Next request gets GPU again rather than spilling over
        alloc_gpu_again = yantra.allocate(req)
        assert alloc_gpu_again.device_id == "gpu-0"
        assert alloc_gpu_again.is_spillover is False

    def test_tampered_allocation_release_rejected_and_state_preserved(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        req_gpu = DeviceRequirement(
            preferred_devices=(DeviceType.GPU,),
            supported_devices=(DeviceType.GPU,),
        )
        req_cpu = DeviceRequirement(
            preferred_devices=(DeviceType.CPU,),
            supported_devices=(DeviceType.CPU,),
        )

        # Allocate 1 GPU slot and 1 CPU slot
        real_gpu_alloc = yantra.allocate(req_gpu)
        real_cpu_alloc = yantra.allocate(req_cpu)
        assert real_gpu_alloc.device_id == "gpu-0"
        assert real_cpu_alloc.device_id == "cpu-0"

        # Forge an allocation with real GPU allocation_id and allocator_id, but claiming to be CPU
        forged_alloc = Allocation(
            allocation_id=real_gpu_alloc.allocation_id,
            device_id="cpu-0",  # Claiming CPU instead of GPU
            device_type=DeviceType.CPU,
            is_spillover=real_gpu_alloc.is_spillover,
            allocator_id=real_gpu_alloc.allocator_id,
        )

        # Releasing forged allocation must fail
        with pytest.raises(DoshError) as exc_info:
            yantra.release(forged_alloc)

        err = exc_info.value
        assert err.code is FailureCode.RESOURCE_UNAVAILABLE
        assert "integrity verification failed" in err.message

        # GPU capacity must NOT be released, so a new GPU allocation still fails
        with pytest.raises(DoshError) as exc_info_gpu:
            yantra.allocate(req_gpu)
        assert exc_info_gpu.value.code is FailureCode.RESOURCE_UNAVAILABLE

        # CPU capacity must NOT be corrupted (still 1 CPU slot remaining of 2 total)
        second_cpu_alloc = yantra.allocate(req_cpu)
        assert second_cpu_alloc.device_id == "cpu-0"

        # Authentic release still works normally
        yantra.release(real_gpu_alloc)
        yantra.release(real_cpu_alloc)
        yantra.release(second_cpu_alloc)

    def test_double_release_rejected(self, inventory: DeviceInventory) -> None:
        yantra = Yantra(inventory)
        req = DeviceRequirement(
            preferred_devices=(DeviceType.CPU,),
            supported_devices=(DeviceType.CPU,),
        )

        alloc = yantra.allocate(req)
        yantra.release(alloc)

        # Second release of same allocation must fail
        with pytest.raises(DoshError) as exc_info:
            yantra.release(alloc)

        err = exc_info.value
        assert err.code is FailureCode.RESOURCE_UNAVAILABLE
        assert "not found or already released" in err.message

    def test_foreign_allocation_release_rejected(self, inventory: DeviceInventory) -> None:
        yantra1 = Yantra(inventory)
        yantra2 = Yantra(inventory)
        req = DeviceRequirement(
            preferred_devices=(DeviceType.CPU,),
            supported_devices=(DeviceType.CPU,),
        )

        alloc_from_1 = yantra1.allocate(req)

        # Attempting to release an allocation with a different Yantra manager instance
        with pytest.raises(DoshError) as exc_info:
            yantra2.release(alloc_from_1)

        err = exc_info.value
        assert err.code is FailureCode.RESOURCE_UNAVAILABLE
        assert "not found or already released" in err.message

    def test_invalid_arguments_to_yantra(self) -> None:
        with pytest.raises(TypeError, match="inventory must be a DeviceInventory instance"):
            Yantra("invalid_inventory")  # type: ignore

        inv = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])
        yantra = Yantra(inv)

        with pytest.raises(TypeError, match="requirement must be a DeviceRequirement"):
            yantra.allocate("not_a_requirement")  # type: ignore

        with pytest.raises(TypeError, match="allocation must be an Allocation instance"):
            yantra.release("not_an_allocation")  # type: ignore

    def test_yantra_exports_only_public_symbols(self) -> None:
        expected = {"Allocation", "DeviceInfo", "DeviceInventory", "Yantra"}
        assert set(yantra_module.__all__) == expected
        assert "ResourceAllocator" not in yantra_module.__all__
        for name in expected:
            assert hasattr(yantra_module, name)


class TestYantraExecution:
    @pytest.fixture
    def inventory_1_slot(self) -> DeviceInventory:
        return DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)])

    @pytest.fixture
    def sample_request(self) -> Request:
        return Request(
            request_id="req-1",
            requirement="test_cap",
            inputs=(
                InputRef(
                    input_id="inp-1",
                    source_path=Path("doc.pdf"),
                    display_name="doc.pdf",
                    size_bytes=100,
                ),
            ),
        )

    @pytest.fixture
    def sample_context(self) -> ExecutionContext:
        return ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
        )

    def test_execute_success_allocates_and_releases(
        self,
        inventory_1_slot: DeviceInventory,
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
        )

        class SuccessCapability:
            def __init__(self) -> None:
                self.declaration = decl

            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Result:
                return Result(data="success_output")

        yantra = Yantra(inventory_1_slot)
        cap = SuccessCapability()

        result = yantra.execute(
            capability=cap,
            request=sample_request,
            context=sample_context,
            prior_result=None,
        )

        assert isinstance(result, Result)
        assert result.data == "success_output"

        # Verify device slot was authentically released in finally block:
        # We can immediately allocate the 1 available slot again without error
        re_alloc = yantra.allocate(decl.device_requirement)
        assert re_alloc.device_id == "cpu-0"
        yantra.release(re_alloc)

    def test_execute_failure_releases_allocation_and_preserves_error(
        self,
        inventory_1_slot: DeviceInventory,
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(preferred_devices=(DeviceType.CPU,)),
        )
        original_error = ValueError("Capability crashed during execute")

        class FailingCapability:
            def __init__(self) -> None:
                self.declaration = decl

            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Result:
                raise original_error

        yantra = Yantra(inventory_1_slot)
        cap = FailingCapability()

        with pytest.raises(ValueError) as exc_info:
            yantra.execute(
                capability=cap,
                request=sample_request,
                context=sample_context,
                prior_result=None,
            )

        assert exc_info.value is original_error

        # Verify device slot was cleanly released even upon failure
        re_alloc = yantra.allocate(decl.device_requirement)
        assert re_alloc.device_id == "cpu-0"
        yantra.release(re_alloc)

    def test_execute_invalid_arguments_and_return_types(
        self,
        inventory_1_slot: DeviceInventory,
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        yantra = Yantra(inventory_1_slot)
        decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )

        class BadReturnCapability:
            def __init__(self) -> None:
                self.declaration = decl

            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Any:
                return {"invalid": "not_a_result"}

        with pytest.raises(TypeError, match="capability must be a Capability"):
            yantra.execute(capability="not_a_cap", request=sample_request, context=sample_context)  # type: ignore

        with pytest.raises(TypeError, match="request must be a Request"):
            yantra.execute(capability=BadReturnCapability(), request="not_a_req", context=sample_context)  # type: ignore

        with pytest.raises(TypeError, match="context must be an ExecutionContext"):
            yantra.execute(capability=BadReturnCapability(), request=sample_request, context="not_a_ctx")  # type: ignore

        with pytest.raises(TypeError, match="prior_result must be a Result"):
            yantra.execute(
                capability=BadReturnCapability(),
                request=sample_request,
                context=sample_context,
                prior_result="not_a_res",
            )  # type: ignore

        # Bad return type raises TypeError and releases allocation
        with pytest.raises(TypeError, match="must return a Result instance"):
            yantra.execute(capability=BadReturnCapability(), request=sample_request, context=sample_context)

        # Capacity is restored
        alloc = yantra.allocate(decl.device_requirement)
        yantra.release(alloc)

    def test_execute_preserves_original_exception_when_release_fails(
        self,
        inventory_1_slot: DeviceInventory,
        sample_request: Request,
        sample_context: ExecutionContext,
    ) -> None:
        """When capability fails and release also fails, the capability's primary exception is preserved."""
        from unittest.mock import patch

        yantra = Yantra(inventory_1_slot)
        decl = CapabilityDeclaration(
            capability_id="test_cap",
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
        )
        primary_err = RuntimeError("Real capability crash")

        class FailingCap:
            def __init__(self) -> None:
                self.declaration = decl

            def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Any:
                raise primary_err

        with patch.object(yantra, "release", side_effect=OSError("Device bus failure on release")):
            with pytest.raises(RuntimeError) as exc_info:
                yantra.execute(capability=FailingCap(), request=sample_request, context=sample_context)

        # The primary error from capability is preserved, not masked by the release failure
        assert exc_info.value is primary_err
        # Note attached with release failure details
        assert any("OSError" in note for note in getattr(primary_err, "__notes__", []))
