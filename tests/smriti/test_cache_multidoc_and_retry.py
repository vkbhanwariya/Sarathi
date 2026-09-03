"""Unit tests for multi-document collection digestion and Pravaha retry caching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi.manthan import CapabilityPlan, Manthan
from sarathi.nabhi.pravaha import Pravaha
from sarathi.nabhi.quarantine import QuarantineStore, RetryPolicy
from sarathi.sankalpa import (
    CanonicalDocument,
    CapabilityDeclaration,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.smriti.key import compute_cache_key, compute_prior_result_digest
from sarathi.smriti.store import SmritiCache
from sarathi.yantra import DeviceInventory, Yantra


def test_single_and_multidoc_digest_determinism() -> None:
    doc1 = CanonicalDocument(document_id="doc-1", source_input_id="inp-1", detected_type="application/pdf", text="Hello world")
    doc2 = CanonicalDocument(document_id="doc-2", source_input_id="inp-2", detected_type="application/pdf", text="Second document")

    res_single = Result(data=doc1)
    res_tuple = Result(data=(doc1, doc2))
    res_list = Result(data=[doc1, doc2])

    digest_single_1 = compute_prior_result_digest(res_single)
    digest_single_2 = compute_prior_result_digest(res_single)
    assert digest_single_1 == digest_single_2
    assert len(digest_single_1) == 64

    digest_tuple_1 = compute_prior_result_digest(res_tuple)
    digest_tuple_2 = compute_prior_result_digest(res_tuple)
    assert digest_tuple_1 == digest_tuple_2
    assert len(digest_tuple_1) == 64

    digest_list = compute_prior_result_digest(res_list)
    assert digest_list == digest_tuple_1

    assert digest_single_1 != digest_tuple_1


def test_multidoc_digest_content_sensitivity() -> None:
    doc1 = CanonicalDocument(document_id="doc-1", source_input_id="inp-1", detected_type="application/pdf", text="Hello world")
    doc2_a = CanonicalDocument(document_id="doc-2", source_input_id="inp-2", detected_type="application/pdf", text="Alpha text")
    doc2_b = CanonicalDocument(document_id="doc-2", source_input_id="inp-2", detected_type="application/pdf", text="Beta text")

    res_a = Result(data=(doc1, doc2_a))
    res_b = Result(data=(doc1, doc2_b))

    digest_a = compute_prior_result_digest(res_a)
    digest_b = compute_prior_result_digest(res_b)

    # Must distinguish different upstream content outcomes in batch
    assert digest_a != digest_b


def test_retry_success_populates_smriti_cache(tmp_path: Path) -> None:
    """Verify that when a capability fails then succeeds on retry, the result is cached in Smriti."""
    cache = SmritiCache(cache_dir=tmp_path / "Cache")
    quar_store = QuarantineStore(root=tmp_path / "Quarantine")
    retry_policy = RetryPolicy(max_retries=2, retryable_codes=(FailureCode.EXECUTION_FAILED,))

    # Flaky capability that fails on attempt 0, succeeds on attempt 1
    call_count = 0
    cap_decl = CapabilityDeclaration(
        capability_id="test_cap",
        plugin_id="test.plugin",
        version="1.0.0",
        supported_profiles=(ExecutionProfile.INSTANT,),
    )

    class FlakyCapability:
        declaration = cap_decl

        def execute(self, request: Request, context: ExecutionContext, prior_result: Result | None = None) -> Result:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DoshError(code=FailureCode.EXECUTION_FAILED, message="Transient flake")
            return Result(
                data=CanonicalDocument(
                    document_id="doc-recovered",
                    source_input_id="inp-1",
                    detected_type="text/plain",
                    text="Recovered text",
                )
            )

    flaky_cap = FlakyCapability()
    capabilities = {"test_cap": flaky_cap}

    from sarathi.nabhi.kosh import Kosh
    from sarathi.sankalpa import DeviceType, PluginInfo, SecurityDeclaration
    from sarathi.yantra import DeviceInfo

    kosh = Kosh()
    kosh.register_plugin(
        PluginInfo(
            plugin_id="test.plugin",
            name="Test Plugin",
            version="1.0.0",
            security=SecurityDeclaration(),
            capabilities=("test_cap",),
        )
    )
    kosh.register_capability(cap_decl)
    manthan = Manthan(registry=kosh)

    inventory = DeviceInventory([DeviceInfo(device_id="cpu-0", device_type=DeviceType.CPU, capacity=4)])
    yantra = Yantra(inventory)

    pravaha = Pravaha(
        manthan=manthan,
        yantra=yantra,
        capabilities=capabilities,
        quarantine_store=quar_store,
        retry_policy=retry_policy,
        smriti=cache,
    )

    inp = InputRef(input_id="inp-1", source_path=tmp_path / "doc.txt", display_name="doc.txt", size_bytes=10)
    inp.source_path.write_text("sample content", encoding="utf-8")

    req = Request(
        request_id="req-1",
        requirement="test_cap",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
    )

    plan = CapabilityPlan(
        request_id=req.request_id,
        capability_ids=("test_cap",),
    )
    ctx = ExecutionContext(
        request_id="req-1",
        run_id="run-1",
        trace_id="trace-1",
        span_id="span-1",
        profile=ExecutionProfile.INSTANT,
    )

    # 1. Execute: should fail once, retry, and succeed
    result = pravaha.execute(plan, req, ctx)
    assert result.data is not None
    assert result.data.document_id == "doc-recovered"
    assert call_count == 2

    # 2. Check that result is present in Smriti cache
    cache_key = compute_cache_key(req, "test_cap", "1.0.0")
    cached_res = cache.get(cache_key)
    assert cached_res is not None
    assert cached_res.data.text == "Recovered text"

    # 3. Second execution should hit cache without calling capability again
    ctx2 = ExecutionContext(
        request_id="req-1",
        run_id="run-2",
        trace_id="trace-2",
        span_id="span-2",
        profile=ExecutionProfile.INSTANT,
    )
    result2 = pravaha.execute(plan, req, ctx2)
    assert result2.data.text == "Recovered text"
    assert call_count == 2  # No new execution!
