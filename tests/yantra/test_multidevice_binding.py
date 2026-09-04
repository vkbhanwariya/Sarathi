"""Unit tests for exact multi-device execution binding and backend locator preservation."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class CaptureCapability:
    def __init__(self, requirement: DeviceRequirement) -> None:
        self.declaration = CapabilityDeclaration(
            capability_id="capture_cap",
            plugin_id="test.multi",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=requirement,
        )
        self.captured_context: ExecutionContext | None = None

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.captured_context = context
        return Result(data="ok")


class TestMultiDeviceBinding:
    @pytest.fixture
    def multi_gpu_inventory(self) -> DeviceInventory:
        cpu = DeviceInfo(
            device_id="cpu-0",
            device_type=DeviceType.CPU,
            capacity=4,
            supported_backends=("openvino", "cpu"),
            backend_locators={"cpu": "CPU", "openvino": "CPU"},
        )
        gpu0 = DeviceInfo(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            capacity=1,
            supported_backends=("cuda", "openvino"),
            backend_locators={"cuda": "0", "openvino": "GPU.0"},
        )
        gpu1 = DeviceInfo(
            device_id="gpu-1",
            device_type=DeviceType.GPU,
            capacity=1,
            supported_backends=("cuda", "openvino"),
            backend_locators={"cuda": "1", "openvino": "GPU.1"},
        )
        return DeviceInventory(devices=(cpu, gpu0, gpu1))

    def test_multi_device_locators_preserved_for_each_gpu(
        self, multi_gpu_inventory: DeviceInventory
    ) -> None:
        yantra = Yantra(multi_gpu_inventory)
        yantra.start()
        try:
            req = DeviceRequirement(
                preferred_devices=(DeviceType.GPU,),
                supported_devices=(DeviceType.GPU, DeviceType.CPU),
            )
            alloc1 = yantra.allocate(req)
            assert alloc1.device_id == "gpu-0"
            # Default preferred backend for GPU includes cuda / openvino
            assert alloc1.backend_device_id in ("0", "GPU.0")

            # Allocate second GPU while first is still held
            alloc2 = yantra.allocate(req)
            assert alloc2.device_id == "gpu-1"
            assert alloc2.backend_device_id in ("1", "GPU.1")

            # Verify releasing alloc1 lets another allocation take gpu-0
            yantra.release(alloc1)
            alloc3 = yantra.allocate(req)
            assert alloc3.device_id == "gpu-0"
            assert alloc3.backend_device_id in ("0", "GPU.0")
            yantra.release(alloc2)
            yantra.release(alloc3)
        finally:
            yantra.close()

    def test_execution_propagates_exact_device_binding(
        self, multi_gpu_inventory: DeviceInventory
    ) -> None:
        yantra = Yantra(multi_gpu_inventory)
        yantra.start()
        try:
            cap = CaptureCapability(
                DeviceRequirement(
                    preferred_devices=(DeviceType.GPU,),
                    supported_devices=(DeviceType.GPU, DeviceType.CPU),
                )
            )
            request = Request(
                request_id="req-1",
                requirement="capture_cap",
                inputs=(
                    InputRef(
                        input_id="inp-1",
                        source_path=Path("test.txt"),
                        display_name="test.txt",
                        size_bytes=10,
                    ),
                ),
            )
            ctx = ExecutionContext(run_id="run-1", request_id="req-1", trace_id="trace-1", span_id="span-1")

            res = yantra.execute(capability=cap, request=request, context=ctx)
            assert res.data == "ok"
            assert cap.captured_context is not None
            binding = cap.captured_context.execution_binding
            assert binding is not None
            assert binding.device_id in ("gpu-0", "gpu-1")
            if binding.device_id == "gpu-0":
                assert binding.backend_device_id in ("0", "GPU.0")
            else:
                assert binding.backend_device_id in ("1", "GPU.1")
        finally:
            yantra.close()
