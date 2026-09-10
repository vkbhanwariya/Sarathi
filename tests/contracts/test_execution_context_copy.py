"""Focused regression tests for immutable ExecutionContext copy semantics."""

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sarathi.agni import dispatcher
from sarathi.sankalpa import (
    CancellationToken,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)


def test_execution_context_copy_helpers_preserve_unmodified_state() -> None:
    token = CancellationToken()
    binding = ExecutionBinding(
        device_id="gpu-0",
        device_type=DeviceType.GPU,
        backend="openvino",
        backend_device_id="GPU.0",
        approved_concurrency=2,
    )
    context = ExecutionContext(
        run_id="run-1",
        request_id="req-1",
        trace_id="tr-1",
        span_id="sp-1",
        profile=ExecutionProfile.ACCURATE,
        cancellation_token=token,
        metadata={"source": "test"},
    )

    bound = context.with_execution_binding(binding)
    child = bound.child_span("sp-2", {"stage": "ocr"})
    retry = child.with_retry(quarantine_attempt=1)

    assert bound.execution_binding is binding
    assert child.execution_binding is binding
    assert child.parent_span_id == "sp-1"
    assert child.metadata == {"source": "test", "stage": "ocr"}
    assert retry.execution_binding is binding
    assert retry.cancellation_token is token
    assert retry.profile is ExecutionProfile.ACCURATE
    assert retry.quarantine_attempt == 1
    assert retry.is_retry is True


def test_agni_token_reconciliation_preserves_execution_binding(tmp_path: Path, monkeypatch: Any) -> None:
    """Adding the request token must not discard unrelated supplied context state."""
    input_file = tmp_path / "input.txt"
    input_file.write_text("content", encoding="utf-8")
    output_root = tmp_path / "Output"
    output_root.mkdir()

    token = CancellationToken()
    binding = ExecutionBinding(
        device_id="cpu-0",
        device_type=DeviceType.CPU,
        backend="native",
        backend_device_id="CPU",
    )
    supplied_context = ExecutionContext(
        run_id="run-1",
        request_id="req-1",
        trace_id="tr-1",
        span_id="sp-1",
        execution_binding=binding,
        metadata={"keep": True},
    )
    request = Request(
        request_id="req-1",
        requirement="read_native",
        inputs=(InputRef("inp-1", input_file, "input.txt", input_file.stat().st_size),),
        cancellation_token=token,
    )

    class Workspace:
        output_dir = output_root / "run-1"
        committed_artifacts: tuple[Any, ...] = ()
        is_finalized = False

        def finalize(self, *, success: bool, **_: Any) -> None:
            self.is_finalized = True

    workspace = Workspace()

    class Boundary:
        captured_context: ExecutionContext | None = None

        @contextmanager
        def begin_run(self, **kwargs: Any) -> Iterator[Workspace]:
            self.captured_context = kwargs["context"]
            yield workspace

    class Kavacha:
        def validate_source_destination_overlap(self, *_: Any) -> None:
            return None

    class Manthan:
        def resolve(self, _: Request) -> object:
            return object()

    class Pravaha:
        captured_context: ExecutionContext | None = None

        def execute(self, _: object, __: Request, context: ExecutionContext) -> Result:
            self.captured_context = context
            return Result(data="ok")

    class SettingsStub:
        telemetry_history_enabled = False

    boundary = Boundary()
    pravaha = Pravaha()
    monkeypatch.setattr(dispatcher, "identify_request", lambda req: req)

    result = dispatcher.execute_request(
        request=request,
        context=supplied_context,
        artifact_boundary=boundary,  # type: ignore[arg-type]
        output_root=output_root,
        runtime_root=tmp_path / "Runtime",
        kavacha=Kavacha(),  # type: ignore[arg-type]
        darpana=None,
        manthan=Manthan(),  # type: ignore[arg-type]
        pravaha=pravaha,  # type: ignore[arg-type]
        settings=SettingsStub(),  # type: ignore[arg-type]
    )

    assert result.data == "ok"
    assert boundary.captured_context is not None
    assert boundary.captured_context.cancellation_token is token
    assert boundary.captured_context.execution_binding is binding
    assert boundary.captured_context.metadata == {"keep": True}
    assert pravaha.captured_context is boundary.captured_context
