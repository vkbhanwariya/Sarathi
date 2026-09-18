"""Lifecycle tests for Agni, the application composition root."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.agni import Agni
from sarathi.dosh import DoshError, FailureCode


class MockComponent:
    def __init__(
        self,
        name: str,
        *,
        start_error: BaseException | None = None,
        close_error: BaseException | None = None,
        tracker: list[str] | None = None,
    ) -> None:
        self.name = name
        self.start_error = start_error
        self.close_error = close_error
        self.tracker = tracker
        self.start_count = 0
        self.close_count = 0

    def start(self) -> None:
        self.start_count += 1
        if self.tracker is not None:
            self.tracker.append(f"start:{self.name}")
        if self.start_error is not None:
            raise self.start_error

    def close(self) -> None:
        self.close_count += 1
        if self.tracker is not None:
            self.tracker.append(f"close:{self.name}")
        if self.close_error is not None:
            raise self.close_error


def _bare_agni() -> Agni:
    runtime = object.__new__(Agni)
    runtime._components = {}
    runtime._attempted_component_ids = set()
    runtime._started_component_ids = []
    runtime._closed_component_ids = set()
    runtime._is_started = False
    runtime._is_closed = False
    return runtime


class TestAgniLifecycle:
    def test_registration_and_ordered_start_reverse_close(self) -> None:
        runtime = _bare_agni()
        events: list[str] = []
        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", tracker=events)
        runtime.register_component("c1", c1)
        runtime.register_component("c2", c2)

        assert runtime.registered_component_ids() == ("c1", "c2")
        runtime.start()
        assert runtime.started_component_ids() == ("c1", "c2")
        assert events == ["start:c1", "start:c2"]

        events.clear()
        runtime.close()
        assert events == ["close:c2", "close:c1"]
        assert runtime.is_closed is True

    def test_duplicate_and_invalid_registration_rejected(self) -> None:
        runtime = _bare_agni()
        runtime.register_component("c1", MockComponent("c1"))

        with pytest.raises(DoshError) as exc_info:
            runtime.register_component("c1", MockComponent("duplicate"))
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        with pytest.raises(TypeError, match="component_id must be a string"):
            runtime.register_component(123, MockComponent("bad"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="non-empty string"):
            runtime.register_component("   ", MockComponent("bad"))
        with pytest.raises(TypeError, match="must expose callable"):
            runtime.register_component("bad", object())

    def test_start_failure_rolls_back_and_preserves_original_error(self) -> None:
        runtime = _bare_agni()
        events: list[str] = []
        original = RuntimeError("startup failed")
        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", start_error=original, tracker=events)
        runtime.register_component("c1", c1)
        runtime.register_component("c2", c2)

        with pytest.raises(RuntimeError) as exc_info:
            runtime.start()
        assert exc_info.value is original
        assert events == ["start:c1", "start:c2", "close:c1"]

    def test_close_attempts_all_components_and_raises_first_error(self) -> None:
        runtime = _bare_agni()
        events: list[str] = []
        first = RuntimeError("c2 close failed")
        runtime.register_component("c1", MockComponent("c1", tracker=events))
        runtime.register_component("c2", MockComponent("c2", close_error=first, tracker=events))
        runtime.start()
        events.clear()

        with pytest.raises(RuntimeError) as exc_info:
            runtime.close()
        assert exc_info.value is first
        assert events == ["close:c2", "close:c1"]


def test_retry_context_preserves_execution_binding() -> None:
    """Verify Pravaha retry execution context preserves execution binding and metadata."""
    from pathlib import Path
    from unittest.mock import MagicMock

    from sarathi.nabhi.kosh import Kosh
    from sarathi.nabhi.pravaha.lifecycle import execute_retry_attempt
    from sarathi.nabhi.quarantine import QuarantineRecord, QuarantineStatus, RetryPolicy
    from sarathi.sankalpa import (
        CapabilityDeclaration,
        DeviceType,
        ExecutionBinding,
        ExecutionContext,
        InputRef,
        Request,
        Result,
    )

    request = Request(
        request_id="request-retry",
        requirement="read_native",
        inputs=(InputRef("input-retry", Path("input.txt"), "input.txt", 1),),
    )
    binding = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="openvino",
        backend_device_id="CPU",
        approved_concurrency=2,
    )
    context = ExecutionContext(
        run_id="run-retry",
        request_id=request.request_id,
        trace_id="trace-retry",
        span_id="span-retry",
        metadata={"owner": "test"},
        execution_binding=binding,
    )
    record = QuarantineRecord(
        quarantine_id="quar-retry",
        input_hash="input-hash",
        run_id=context.run_id,
        request_id=context.request_id,
        trace_id=context.trace_id,
        capability_id="read_native",
        plugin_id="test.plugin",
        failure_code=FailureCode.EXECUTION_FAILED,
        profile=context.profile.value,
        attempt_count=0,
        max_retries=1,
        status=QuarantineStatus.QUARANTINED,
        created_at_utc="2026-09-11T00:00:00+00:00",
        updated_at_utc="2026-09-11T00:00:00+00:00",
    )
    capability = MagicMock()
    capability.declaration = CapabilityDeclaration(
        capability_id="read_native",
        plugin_id="test.plugin",
        version="1.0.0",
        supported_profiles=(context.profile,),
    )
    quarantine_store = MagicMock()
    quarantine_store.update_status.return_value = record
    yantra = MagicMock()
    yantra.execute.return_value = Result(data="ok")

    execute_retry_attempt(
        cap=capability,
        request=request,
        context=context,
        record=record,
        prior_result=None,
        quarantine_store=quarantine_store,
        retry_policy=RetryPolicy(max_retries=1),
        yantra=yantra,
        darpana=None,
        kavacha=None,
        registry=Kosh(),
    )

    retry_context = yantra.execute.call_args.kwargs["context"]
    assert retry_context.execution_binding is binding
    assert retry_context.metadata == context.metadata
    assert retry_context.parent_span_id == context.span_id
    assert retry_context.quarantine_attempt == 1
    assert retry_context.is_retry is True


class TestYantraLifecycleUnderAgni:
    def test_yantra_started_and_closed_by_agni(self, tmp_path: Path) -> None:
        from sarathi.sankalpa import DeviceType
        from sarathi.yantra import DeviceInfo, DeviceInventory

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

    def test_end_to_end_execution_binding_propagation(self, tmp_path: Path) -> None:
        from sarathi.sankalpa import (
            CanonicalDocument,
            CapabilityDeclaration,
            DeviceRequirement,
            DeviceType,
            ExecutionBinding,
            ExecutionContext,
            ExecutionProfile,
            InputRef,
            PluginInfo,
            Request,
            Result,
        )
        from sarathi.yantra import DeviceInfo, DeviceInventory

        inventory = DeviceInventory(
            [
                DeviceInfo(device_id="gpu-0", device_type=DeviceType.GPU, capacity=2),
                DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4),
            ]
        )

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
            output_root=tmp_path / "output",
            inventory=inventory,
            plugins=[test_plugin],
            capabilities={"test_cap": cap},
        )

        req = Request(
            request_id="req-e2e",
            requirement="test_cap",
            inputs=(
                InputRef(
                    input_id="in-1",
                    source_path=inp_file,
                    display_name="test.txt",
                    size_bytes=5,
                    media_type="text/plain",
                ),
            ),
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
