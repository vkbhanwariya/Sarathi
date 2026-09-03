"""Integration tests for Yantra lifecycle under Prana in Agni bootstrap and end-to-end device binding."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sarathi.agni import Agni
from sarathi.sankalpa import (
    CanonicalDocument,
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    PluginInfo,
    Request,
    Result,
)
from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra


class TestYantraLifecycleUnderAgni:
    def test_yantra_started_and_closed_by_agni(self, tmp_path) -> None:
        inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=2)])
        agni = Agni(
            runtime_root=tmp_path / "runtime",
            inventory=inventory,
        )

        assert agni._yantra.is_started is False
        assert agni._yantra.is_closed is False

        with agni as runtime:
            assert runtime.is_started is True
            assert runtime._yantra.is_started is True
            assert runtime._yantra.is_closed is False

        assert agni.is_closed is True
        assert agni._yantra.is_closed is True
        assert agni._yantra.is_started is False

    def test_end_to_end_execution_binding_propagation(self, tmp_path) -> None:
        inventory = DeviceInventory([
            DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=2),
            DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
        ])

        class MockCapability:
            def __init__(self, decl: CapabilityDeclaration) -> None:
                self._decl = decl
                self.captured_bindings: list[ExecutionBinding | None] = []

            @property
            def declaration(self) -> CapabilityDeclaration:
                return self._decl

            def execute(
                self,
                request: Request,
                context: ExecutionContext,
                prior_result: Result | None = None,
            ) -> Result:
                self.captured_bindings.append(context.execution_binding)
                return Result(
                    data=CanonicalDocument(
                        document_id="doc-out",
                        source_input_id=request.inputs[0].input_id,
                        text="Processed Output",
                    ),
                )

        decl = CapabilityDeclaration(
            plugin_id="shakti.test",
            capability_id="test_cap",
            version="1.0.0",
            supported_profiles=(ExecutionProfile.INSTANT,),
            device_requirement=DeviceRequirement(
                preferred_devices=(DeviceType.GPU,),
                supported_devices=(DeviceType.GPU, DeviceType.CPU),
                supported_backends=("cuda",),
            ),
        )
        cap = MockCapability(decl)

        inp_file = tmp_path / "test.txt"
        inp_file.write_text("dummy", encoding="utf-8")

        test_plugin = PluginInfo(
            plugin_id="shakti.test",
            name="Test Plugin",
            version="1.0.0",
            capabilities=("test_cap",),
        )
        agni = Agni(
            runtime_root=tmp_path / "runtime",
            inventory=inventory,
            plugins=[test_plugin],
            capabilities={"test_cap": cap},
        )

        req = Request(
            request_id="req-e2e",
            requirement="test_cap",
            inputs=(InputRef(input_id="in-1", source_path=inp_file, display_name="test.txt", size_bytes=5, media_type="text/plain"),),
        )

        res = agni.execute(req)
        assert res.data is not None
        assert len(cap.captured_bindings) == 1
        binding = cap.captured_bindings[0]
        assert binding is not None
        assert binding.device_id == "gpu-0"
        assert binding.device_type == DeviceType.GPU
        assert binding.backend == "cuda"
        assert binding.is_spillover is False
