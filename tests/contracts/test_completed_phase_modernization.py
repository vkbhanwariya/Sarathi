"""Regression coverage for the completed-phase modernization sweep."""

import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

from sarathi.dosh import FailureCode
from sarathi.nabhi.kosh import Kosh
from sarathi.nabhi.pravaha.lifecycle import execute_retry_attempt
from sarathi.nabhi.quarantine import (
    QuarantineRecord,
    QuarantineStatus,
    QuarantineStore,
    RetryPolicy,
)
from sarathi.sankalpa import (
    CanonicalDocument,
    DeviceType,
    ExecutionBinding,
    ExecutionContext,
    InputRef,
    Request,
    Result,
)
from sarathi.smriti.key import CacheKey
from sarathi.smriti.memory import MemoryCache
from sarathi.smriti.policy import CachePolicy
from sarathi.smriti.store import SQLiteCacheStore


class _CapturingYantra:
    def __init__(self) -> None:
        self.context: ExecutionContext | None = None

    def execute(self, *, capability, request, context, prior_result=None) -> Result:
        self.context = context
        return Result(
            data=CanonicalDocument(
                document_id="retry-result",
                source_input_id=request.inputs[0].input_id,
                text="ok",
            )
        )


def _cache_key(name: str) -> CacheKey:
    return CacheKey(
        capability_id="read_native",
        fingerprint=f"fp-{name}",
        profile="instant",
        key_hash=f"hash-{name}",
    )


def _cache_result(label: str, metadata=None) -> Result:
    return Result(
        data=CanonicalDocument(
            document_id=f"doc-{label}",
            source_input_id=f"input-{label}",
            text=label,
            metadata=metadata or {},
        )
    )


def test_retry_context_preserves_execution_binding(tmp_path: Path) -> None:
    input_ref = InputRef(
        input_id="input-retry",
        source_path=tmp_path / "input.txt",
        display_name="input.txt",
        size_bytes=1,
    )
    request = Request(
        request_id="request-retry",
        requirement="read_native",
        inputs=(input_ref,),
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
    store = QuarantineStore(tmp_path / "quarantine")
    store.quarantine(record)
    yantra = _CapturingYantra()

    result, updated_record = execute_retry_attempt(
        cap=object(),
        request=request,
        context=context,
        record=record,
        prior_result=None,
        quarantine_store=store,
        retry_policy=RetryPolicy(max_retries=1),
        yantra=yantra,
        darpana=None,
        kavacha=None,
        registry=Kosh(),
    )

    assert result is not None
    assert updated_record.status is QuarantineStatus.RELEASED
    assert yantra.context is not None
    assert yantra.context.execution_binding is binding
    assert yantra.context.metadata == context.metadata
    assert yantra.context.parent_span_id == context.span_id
    assert yantra.context.quarantine_attempt == 1
    assert yantra.context.is_retry is True


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


def test_memory_cache_copies_nested_mutable_metadata_locally() -> None:
    source_items = ["original"]
    nested_proxy = MappingProxyType({"items": source_items})
    result = _cache_result("copy", metadata={"nested": nested_proxy})
    cache = MemoryCache()
    key = _cache_key("copy")

    cache.put(key, result)
    source_items.append("source-mutated")

    first = cache.get(key)
    assert first is not None
    assert first.data.metadata["nested"]["items"] == ["original"]

    first.data.metadata["nested"]["items"].append("retrieved-mutated")
    second = cache.get(key)
    assert second is not None
    assert second.data.metadata["nested"]["items"] == ["original"]


def test_sqlite_refresh_at_capacity_does_not_evict_other_key(tmp_path: Path) -> None:
    store = SQLiteCacheStore(
        db_path=tmp_path / "smriti.db",
        policy=CachePolicy(max_entries_l2=2),
    )
    key_a = _cache_key("a")
    key_b = _cache_key("b")
    store.put(key_a, _cache_result("a"))
    store.put(key_b, _cache_result("b"))

    store.put(key_b, _cache_result("b-refreshed"))

    assert store.get(key_a) is not None
    refreshed = store.get(key_b)
    assert refreshed is not None
    assert refreshed.data.text == "b-refreshed"
    with store._lock, store._get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM smriti_entries").fetchone()[0]
    assert count == 2
    store.close()
