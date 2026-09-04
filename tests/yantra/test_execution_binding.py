"""Unit tests for ExecutionBinding and its propagation through Yantra."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sarathi.darpana import Darpana
from sarathi.sankalpa import (
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class MockRecordingCapability:
    """Test capability that captures the ExecutionContext it receives."""

    def __init__(
        self,
        capability_id: str = "test_cap",
        device_requirement: DeviceRequirement | None = None,
    ) -> None:
        self.declaration = CapabilityDeclaration(
            capability_id=capability_id,
            plugin_id="test.plugin",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=device_requirement or DeviceRequirement(),
        )
        self.captured_context: ExecutionContext | None = None
        self.captured_request: Request | None = None

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        self.captured_context = context
        self.captured_request = request
        return Result(data=None)


class TestExecutionBindingContract:
    def test_execution_binding_valid_and_immutable(self) -> None:
        binding = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="openvino",
            backend_device_id="GPU",
            is_spillover=False,
        )
        assert binding.device_id == "gpu-0"
        assert binding.device_type == DeviceType.GPU
        assert binding.backend == "openvino"
        assert binding.backend_device_id == "GPU"
        assert binding.is_spillover is False

        with pytest.raises(AttributeError):
            binding.device_id = "cpu-0"  # type: ignore

    def test_execution_binding_validation(self) -> None:
        with pytest.raises(ValueError, match="device_id must be a non-empty string"):
            ExecutionBinding(
                device_id="",
                device_type=DeviceType.CPU,
                backend="cpu",
                backend_device_id="CPU",
            )

        with pytest.raises(TypeError, match="device_type must be a DeviceType"):
            ExecutionBinding(
                device_id="cpu-0",
                device_type="cpu",  # type: ignore
                backend="cpu",
                backend_device_id="CPU",
            )

        with pytest.raises(ValueError, match="backend must be a non-empty string"):
            ExecutionBinding(
                device_id="cpu-0",
                device_type=DeviceType.CPU,
                backend="   ",
                backend_device_id="CPU",
            )

        with pytest.raises(ValueError, match="backend_device_id must be a non-empty string"):
            ExecutionBinding(
                device_id="cpu-0",
                device_type=DeviceType.CPU,
                backend="cpu",
                backend_device_id="",
            )

        with pytest.raises(TypeError, match="is_spillover must be a bool"):
            ExecutionBinding(
                device_id="cpu-0",
                device_type=DeviceType.CPU,
                backend="cpu",
                backend_device_id="CPU",
                is_spillover="false",  # type: ignore
            )


class TestExecutionContextBindingIntegration:
    def test_context_default_binding_is_none(self) -> None:
        ctx = ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
        )
        assert ctx.execution_binding is None

    def test_context_rejects_invalid_binding_type(self) -> None:
        with pytest.raises(TypeError, match="execution_binding must be an ExecutionBinding instance"):
            ExecutionContext(
                run_id="run-1",
                request_id="req-1",
                trace_id="tr-1",
                span_id="sp-1",
                execution_binding="not-a-binding",  # type: ignore
            )

    def test_with_execution_binding_attaches_binding(self) -> None:
        ctx = ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
            profile=ExecutionProfile.ACCURATE,
            metadata={"test": "true"},
        )
        binding = ExecutionBinding(
            device_id="cpu-0",
            device_type=DeviceType.CPU,
            backend="cpu",
            backend_device_id="CPU",
            is_spillover=False,
        )
        bound = ctx.with_execution_binding(binding)

        assert bound.execution_binding == binding
        assert bound.run_id == ctx.run_id
        assert bound.request_id == ctx.request_id
        assert bound.trace_id == ctx.trace_id
        assert bound.span_id == ctx.span_id
        assert bound.profile == ExecutionProfile.ACCURATE
        assert bound.metadata["test"] == "true"
        # Original context unchanged
        assert ctx.execution_binding is None

    def test_with_execution_binding_rejects_invalid_type(self) -> None:
        ctx = ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-1",
        )
        with pytest.raises(TypeError, match="binding must be an ExecutionBinding instance"):
            ctx.with_execution_binding("invalid")  # type: ignore

    def test_child_span_and_retry_preserve_binding(self) -> None:
        binding = ExecutionBinding(
            device_id="gpu-0",
            device_type=DeviceType.GPU,
            backend="openvino",
            backend_device_id="GPU",
            is_spillover=False,
        )
        ctx = ExecutionContext(
            run_id="run-1",
            request_id="req-1",
            trace_id="tr-1",
            span_id="sp-root",
            execution_binding=binding,
        )

        child = ctx.child_span("sp-child")
        assert child.execution_binding == binding
        assert child.parent_span_id == "sp-root"

        retry = ctx.with_retry(quarantine_attempt=1)
        assert retry.execution_binding == binding
        assert retry.is_retry is True
        assert retry.quarantine_attempt == 1


class TestYantraExecutionBindingPropagation:
    def test_yantra_execute_attaches_binding_to_capability(self) -> None:
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2),
            ]
        )
        darpana = Darpana(capacity=100)
        yantra = Yantra(inventory, darpana=darpana)

        cap = MockRecordingCapability(
            capability_id="test_cap",
            device_requirement=DeviceRequirement(
                preferred_devices=(DeviceType.CPU,),
                supported_devices=(DeviceType.CPU,),
            ),
        )

        ctx = ExecutionContext(
            run_id="run-10",
            request_id="req-10",
            trace_id="tr-10",
            span_id="sp-10",
        )
        req = Request(
            request_id="req-10",
            requirement="test_cap",
            inputs=[InputRef(input_id="in-1", source_path=Path("doc.pdf"), display_name="doc.pdf", size_bytes=10)],
        )

        result = yantra.execute(capability=cap, request=req, context=ctx)
        assert isinstance(result, Result)

        # Assert context received by capability has the execution binding
        received_ctx = cap.captured_context
        assert received_ctx is not None
        assert received_ctx.execution_binding is not None
        assert received_ctx.execution_binding.device_id == "cpu-0"
        assert received_ctx.execution_binding.device_type == DeviceType.CPU
        assert received_ctx.execution_binding.backend == "cpu"
        assert received_ctx.execution_binding.backend_device_id == "CPU"
        assert received_ctx.execution_binding.is_spillover is False

    def test_yantra_execute_gpu_and_spillover_binding(self) -> None:
        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=1),
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2),
            ]
        )
        yantra = Yantra(inventory)

        # 1. OCR capability on GPU
        ocr_cap = MockRecordingCapability(
            capability_id="ocr",
            device_requirement=DeviceRequirement(
                preferred_devices=(DeviceType.GPU,),
                supported_devices=(DeviceType.GPU, DeviceType.CPU),
            ),
        )
        ctx = ExecutionContext(run_id="r1", request_id="req1", trace_id="t1", span_id="s1")
        req = Request(request_id="req1", requirement="ocr", inputs=[InputRef(input_id="i1", source_path=Path("p.pdf"), display_name="p.pdf", size_bytes=1)])

        yantra.execute(capability=ocr_cap, request=req, context=ctx)
        assert ocr_cap.captured_context is not None
        binding = ocr_cap.captured_context.execution_binding
        assert binding is not None
        assert binding.device_id == "gpu-0"
        assert binding.device_type == DeviceType.GPU
        assert binding.backend == "openvino"
        assert binding.backend_device_id in ("GPU.0", "GPU")
        assert binding.is_spillover is False

        # 2. Spillover when GPU is exhausted
        # Allocate GPU slot directly so it becomes busy
        alloc_gpu = yantra.allocate(
            DeviceRequirement(
                preferred_devices=(DeviceType.GPU,),
                supported_devices=(DeviceType.GPU,),
            )
        )
        try:
            spillover_cap = MockRecordingCapability(
                capability_id="translation",
                device_requirement=DeviceRequirement(
                    preferred_devices=(DeviceType.GPU,),
                    supported_devices=(DeviceType.GPU, DeviceType.CPU),
                ),
            )
            yantra.execute(capability=spillover_cap, request=req, context=ctx)
            assert spillover_cap.captured_context is not None
            spill_binding = spillover_cap.captured_context.execution_binding
            assert spill_binding is not None
            assert spill_binding.device_id == "cpu-0"
            assert spill_binding.device_type == DeviceType.CPU
            assert spill_binding.is_spillover is True
        finally:
            yantra.release(alloc_gpu)
