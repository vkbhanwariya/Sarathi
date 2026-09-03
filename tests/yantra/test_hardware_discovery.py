"""Unit tests for Yantra hardware discovery and runtime compatibility."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
from sarathi.shakti.bank_statements.plugin import CAPABILITY_DECLARATION as BANK_DECL
from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION as FONT_DECL
from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION as NATIVE_DECL
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION as OCR_DECL
from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION as TRANSLATION_DECL
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class MockTestCapability:
    def __init__(self, declaration: CapabilityDeclaration) -> None:
        self.declaration = declaration

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        return Result(data=None)


class TestHardwareDiscovery:
    def test_default_inventory_without_accelerator_flag_is_cpu_only(self) -> None:
        inv = DeviceInventory.default_inventory(detect_accelerators=False)
        assert len(inv) == 1
        assert inv.devices[0].device_type == DeviceType.CPU
        assert inv.devices[0].device_id == "cpu-0"
        assert inv.devices[0].capacity >= 1

    def test_discovery_openvino_cpu_only(self) -> None:
        mock_core = MagicMock()
        mock_core.available_devices = ["CPU"]
        with patch.dict("sys.modules", {"openvino": MagicMock(Core=MagicMock(return_value=mock_core))}):
            inv = DeviceInventory.default_inventory(detect_accelerators=True)
            assert len(inv) == 1
            assert inv.devices[0].device_type == DeviceType.CPU

    def test_discovery_openvino_cpu_and_gpu(self) -> None:
        mock_core = MagicMock()
        mock_core.available_devices = ["CPU", "GPU.0"]
        with patch.dict("sys.modules", {"openvino": MagicMock(Core=MagicMock(return_value=mock_core))}):
            inv = DeviceInventory.default_inventory(detect_accelerators=True)
            assert len(inv) == 2
            dev_types = [d.device_type for d in inv.devices]
            assert DeviceType.CPU in dev_types
            assert DeviceType.GPU in dev_types
            gpu_dev = inv.get_device("gpu-0")
            assert gpu_dev is not None
            assert gpu_dev.capacity == 2

    def test_discovery_openvino_cpu_and_npu(self) -> None:
        mock_core = MagicMock()
        mock_core.available_devices = ["CPU", "NPU"]
        with patch.dict("sys.modules", {"openvino": MagicMock(Core=MagicMock(return_value=mock_core))}):
            inv = DeviceInventory.default_inventory(detect_accelerators=True)
            assert len(inv) == 2
            dev_types = [d.device_type for d in inv.devices]
            assert DeviceType.CPU in dev_types
            assert DeviceType.NPU in dev_types
            npu_dev = inv.get_device("npu-0")
            assert npu_dev is not None
            assert npu_dev.capacity == 2

    def test_discovery_openvino_cpu_gpu_npu(self) -> None:
        mock_core = MagicMock()
        mock_core.available_devices = ["CPU", "GPU", "NPU"]
        with patch.dict("sys.modules", {"openvino": MagicMock(Core=MagicMock(return_value=mock_core))}):
            inv = DeviceInventory.default_inventory(detect_accelerators=True)
            assert len(inv) == 3
            dev_types = [d.device_type for d in inv.devices]
            assert dev_types == [DeviceType.CPU, DeviceType.GPU, DeviceType.NPU]

    def test_discovery_failure_falls_back_to_cpu_only(self) -> None:
        with patch.dict("sys.modules", {"openvino": None, "ctranslate2": None}):
            inv = DeviceInventory.default_inventory(detect_accelerators=True)
            assert len(inv) == 1
            assert inv.devices[0].device_type == DeviceType.CPU

    def test_discovery_cuda_when_openvino_absent(self) -> None:
        mock_ct2 = MagicMock()
        mock_ct2.get_cuda_device_count.return_value = 1
        with patch.dict("sys.modules", {"openvino": None, "ctranslate2": mock_ct2}):
            inv = DeviceInventory.default_inventory(detect_accelerators=True)
            assert len(inv) == 2
            assert inv.devices[0].device_type == DeviceType.CPU
            assert inv.devices[1].device_type == DeviceType.GPU
            assert inv.devices[1].device_id == "gpu-cuda-0"


class TestRuntimeCompatibility:
    @pytest.fixture
    def full_inventory(self) -> DeviceInventory:
        return DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
                DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=2),
                DeviceInfo(device_id="npu-0", device_type=DeviceType.NPU, capacity=2),
            ]
        )

    def test_gpu_available_but_cpu_only_capability_allocates_cpu(self, full_inventory: DeviceInventory) -> None:
        yantra = Yantra(full_inventory)

        # Native extraction, bank, font are CPU-only
        for decl in (NATIVE_DECL, BANK_DECL, FONT_DECL):
            alloc = yantra.allocate(decl.device_requirement)
            try:
                assert alloc.device_type == DeviceType.CPU
                assert alloc.device_id == "cpu-0"
            finally:
                yantra.release(alloc)

    def test_npu_available_but_unsupported_backend_never_selects_npu(self, full_inventory: DeviceInventory) -> None:
        yantra = Yantra(full_inventory)

        # Translation declares CPU + GPU, but NO NPU
        assert DeviceType.NPU not in TRANSLATION_DECL.device_requirement.supported_devices
        alloc_trans = yantra.allocate(TRANSLATION_DECL.device_requirement)
        try:
            assert alloc_trans.device_type in (DeviceType.CPU, DeviceType.GPU)
            assert alloc_trans.device_type != DeviceType.NPU
        finally:
            yantra.release(alloc_trans)

        # OCR declares CPU + GPU, but NO NPU
        assert DeviceType.NPU not in OCR_DECL.device_requirement.supported_devices
        alloc_ocr = yantra.allocate(OCR_DECL.device_requirement)
        try:
            assert alloc_ocr.device_type in (DeviceType.CPU, DeviceType.GPU)
            assert alloc_ocr.device_type != DeviceType.NPU
        finally:
            yantra.release(alloc_ocr)

    def test_compatible_gpu_available_selected_according_to_policy(self, full_inventory: DeviceInventory) -> None:
        yantra = Yantra(full_inventory)

        # Capability with preferred GPU
        req = DeviceRequirement(
            preferred_devices=(DeviceType.GPU,),
            supported_devices=(DeviceType.GPU, DeviceType.CPU),
        )
        alloc = yantra.allocate(req)
        try:
            assert alloc.device_type == DeviceType.GPU
            assert alloc.device_id == "gpu-0"
            assert alloc.is_spillover is False
        finally:
            yantra.release(alloc)

    def test_declarations_truthfulness(self) -> None:
        # Translation must not claim NPU
        assert DeviceType.NPU not in TRANSLATION_DECL.device_requirement.supported_devices
        # OCR must support GPU via OpenVINO, but not NPU
        assert DeviceType.GPU in OCR_DECL.device_requirement.supported_devices
        assert DeviceType.NPU not in OCR_DECL.device_requirement.supported_devices
