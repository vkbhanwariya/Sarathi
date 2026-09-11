"""Focused regressions for completed-phase modernization fixes."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from sarathi.dosh import FailureCode
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


def test_retry_context_preserves_execution_binding() -> None:
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


def test_importing_smriti_does_not_patch_global_deepcopy_dispatch() -> None:
    code = """
import copy
from types import MappingProxyType
before = copy._deepcopy_dispatch.get(MappingProxyType)
import sarathi.smriti.memory
assert copy._deepcopy_dispatch.get(MappingProxyType) is before
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
