"""Unit tests for Yantra — Resource & Execution Manager Phase 1."""

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import DeviceRequirement, DeviceType
from sarathi.yantra import (
    Allocation,
    DeviceInfo,
    DeviceInventory,
    ResourceAllocator,
    Yantra,
)
import sarathi.yantra as yantra_module


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
        return DeviceInventory([
            DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=1),
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2),
        ])

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
        alloc1 = yantra.allocate(req)  # GPU slot 1/1
        alloc2 = yantra.allocate(req)  # CPU slot 1/2
        alloc3 = yantra.allocate(req)  # CPU slot 2/2

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

        # Attempting to release an allocation with a different allocator instance
        with pytest.raises(DoshError) as exc_info:
            yantra2.release(alloc_from_1)

        err = exc_info.value
        assert err.code is FailureCode.RESOURCE_UNAVAILABLE
        assert "Cannot release foreign allocation" in err.message

    def test_invalid_arguments_to_yantra(self) -> None:
        with pytest.raises(TypeError, match="inventory must be a DeviceInventory instance"):
            Yantra("invalid_inventory")  # type: ignore

        inv = DeviceInventory([
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=1)
        ])
        yantra = Yantra(inv)

        with pytest.raises(TypeError, match="requirement must be a DeviceRequirement"):
            yantra.allocate("not_a_requirement")  # type: ignore

        with pytest.raises(TypeError, match="allocation must be an Allocation instance"):
            yantra.release("not_an_allocation")  # type: ignore

    def test_yantra_exports(self) -> None:
        expected = {"Allocation", "DeviceInfo", "DeviceInventory", "ResourceAllocator", "Yantra"}
        assert set(yantra_module.__all__) == expected
        for name in expected:
            assert hasattr(yantra_module, name)
