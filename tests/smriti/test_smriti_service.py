"""Tests for Smriti Two-Tier (L1 Memory + L2 SQLite) Cache Service."""

from dataclasses import dataclass
from pathlib import Path

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.smriti.key import compute_cache_key
from sarathi.smriti.store import SmritiCache


@dataclass(frozen=True)
class UnsupportedDataType:
    val: str


def test_l1_l2_two_tier_caching_and_promotion(tmp_path: Path) -> None:
    cache_dir = tmp_path / "Cache"
    cache = SmritiCache(cache_dir=cache_dir)

    inp = InputRef(input_id="inp-1", source_path=tmp_path / "a.txt", display_name="a.txt", size_bytes=100)
    req = Request(request_id="req-1", requirement="read_native", inputs=(inp,), profile=ExecutionProfile.INSTANT)
    key = compute_cache_key(req, "read_native", "1.0.0")

    doc = CanonicalDocument(document_id="doc-1", source_input_id="inp-1", text="Cached text payload")
    orig_res = Result(data=doc)

    # Miss before put
    res, tier = cache.get_with_tier(key)
    assert res is None
    assert tier is None

    # Put into cache (populates L1 and L2)
    cache.put(key, orig_res)

    # L1 Hit
    l1_res, l1_tier = cache.get_with_tier(key)
    assert l1_res is not None
    assert l1_tier == "l1"
    assert isinstance(l1_res.data, CanonicalDocument)
    assert l1_res.data.text == "Cached text payload"

    # Invalidate only L1 to verify L2 persistence and promotion
    cache._l1.invalidate()
    assert len(cache._l1) == 0

    # L2 Hit (promotes to L1)
    promoted_res, promoted_tier = cache.get_with_tier(key)
    assert promoted_res is not None
    assert promoted_tier == "l2"
    assert isinstance(promoted_res.data, CanonicalDocument)
    assert promoted_res.data.text == "Cached text payload"
    assert len(cache._l1) == 1


def test_unsupported_result_skipped_without_corrupting_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "Cache"
    cache = SmritiCache(cache_dir=cache_dir)

    inp = InputRef(input_id="inp-1", source_path=tmp_path / "a.txt", display_name="a.txt", size_bytes=100)
    req = Request(request_id="req-1", requirement="custom", inputs=(inp,), profile=ExecutionProfile.INSTANT)
    key = compute_cache_key(req, "custom", "1.0.0")

    unsupported_res = Result(data=UnsupportedDataType(val="custom"))

    # Put unsupported result: must be safely skipped
    cache.put(key, unsupported_res)

    # Cache get must return None rather than data=None
    res = cache.get(key)
    assert res is None


def test_invalidation_by_capability(tmp_path: Path) -> None:
    cache_dir = tmp_path / "Cache"
    cache = SmritiCache(cache_dir=cache_dir)

    inp = InputRef(input_id="inp-1", source_path=tmp_path / "a.txt", display_name="a.txt", size_bytes=100)
    req = Request(request_id="req-1", requirement="read_native", inputs=(inp,), profile=ExecutionProfile.INSTANT)
    key_native = compute_cache_key(req, "read_native", "1.0.0")
    key_ocr = compute_cache_key(req, "ocr", "1.0.0")

    res = Result(data=CanonicalDocument(document_id="d-1", source_input_id="inp-1", text="text"))

    cache.put(key_native, res)
    cache.put(key_ocr, res)

    count = cache.invalidate(capability_id="read_native")
    assert count >= 1

    assert cache.get(key_native) is None
    assert cache.get(key_ocr) is not None


def test_memory_cache_defensive_deep_copy() -> None:
    """L1 isolates nested mutable metadata on both put and get."""
    from sarathi.smriti.memory import MemoryCache

    source_items = ["original"]
    doc = CanonicalDocument(
        document_id="d-iso",
        source_input_id="inp-1",
        text="original",
        metadata={"items": source_items},
    )
    inp = InputRef(input_id="inp-1", source_path=Path("dummy.txt"), display_name="dummy.txt", size_bytes=10)
    req = Request(request_id="r-iso", requirement="read_native", inputs=(inp,))
    key = compute_cache_key(req, "read_native", "1.0.0")

    cache = MemoryCache()
    cache.put(key, Result(data=doc))
    source_items.append("source-mutated")

    first = cache.get(key)
    assert first is not None
    assert first.data.metadata["items"] == ["original"]

    first.data.metadata["items"].append("retrieved-mutated")
    second = cache.get(key)
    assert second is not None
    assert second.data.metadata["items"] == ["original"]


def test_smriti_l2_to_l1_promotion_preserves_created_at(tmp_path: Path) -> None:
    """Verify promotion from L2 to L1 preserves the original creation timestamp."""
    import time

    from sarathi.smriti.store import SmritiCache

    cache = SmritiCache(cache_dir=tmp_path)
    doc = CanonicalDocument(document_id="d-ts", source_input_id="inp-1", text="text")
    inp = InputRef(input_id="inp-1", source_path=tmp_path / "a.txt", display_name="a.txt", size_bytes=10)
    req = Request(request_id="r-ts", requirement="read_native", inputs=(inp,))
    key = compute_cache_key(req, "read_native", "1.0.0")

    orig_res = Result(data=doc)
    cache.put(key, orig_res)

    # Clear L1 memory tier so next lookup hits L2
    cache._l1.invalidate()
    assert len(cache._l1) == 0

    # Retrieve from L2 and promote to L1
    res, tier = cache.get_with_tier(key)
    assert tier == "l2"
    assert res is not None

    # L1 must now hold the promoted entry with the L2 creation timestamp
    l1_entry = cache._l1._cache.get(key.key_hash)
    assert l1_entry is not None
    # Timestamp must not be artificially advanced
    assert l1_entry.created_at <= time.time()


def test_metadata_stype_dictionary_collision_safe_roundtrip() -> None:
    """Verify user metadata dictionary containing '__stype__' serializes and deserializes safely."""
    from sarathi.smriti.serialization import deserialize_result, serialize_result

    user_meta = {"__stype__": "custom_payload", "val": 42, "description": "test"}
    doc = CanonicalDocument(
        document_id="d-stype",
        source_input_id="inp-1",
        metadata={"user_dict": user_meta},
    )
    orig_res = Result(data=doc)
    serialized = serialize_result(orig_res)
    deserialized = deserialize_result(serialized)

    assert isinstance(deserialized.data, CanonicalDocument)
    assert deserialized.data.metadata["user_dict"] == user_meta


def test_smriti_cache_clear_purges_both_tiers(tmp_path: Path) -> None:
    """Verify SmritiCache.clear() purges entries across both L1 memory and L2 SQLite tiers."""
    cache_dir = tmp_path / "Cache"
    cache = SmritiCache(cache_dir=cache_dir)

    inp = InputRef(input_id="inp-clr", source_path=tmp_path / "clr.txt", display_name="clr.txt", size_bytes=50)
    req = Request(request_id="req-clr", requirement="read_native", inputs=(inp,))
    key = compute_cache_key(req, "read_native", "1.0.0")

    doc = CanonicalDocument(document_id="doc-clr", source_input_id="inp-clr", text="test-clear")
    orig_res = Result(data=doc)
    cache.put(key, orig_res)

    assert cache.get(key) is not None

    cleared_count = cache.clear()
    assert cleared_count >= 1
    assert cache.get(key) is None


def test_importing_smriti_does_not_patch_global_deepcopy_dispatch() -> None:
    """Verify importing Smriti memory does not monkey-patch standard library copy dispatch."""
    import subprocess
    import sys

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


def test_ttl_validity_rule() -> None:
    from sarathi.smriti.policy import CachePolicy

    policy = CachePolicy(ttl_seconds=100)
    assert policy.is_valid(created_at=1000.0, current_time=1050.0) is True
    assert policy.is_valid(created_at=1000.0, current_time=1101.0) is False


def test_unlimited_ttl() -> None:
    from sarathi.smriti.policy import CachePolicy

    policy = CachePolicy(ttl_seconds=None)
    assert policy.is_valid(created_at=1000.0, current_time=999999.0) is True


def test_pipeline_caches_and_records_factual_telemetry(tmp_path: Path) -> None:
    from sarathi.agni import Agni
    from sarathi.darpana import Darpana

    runtime_dir = tmp_path / "Runtime"
    output_dir = tmp_path / "Output"
    darpana = Darpana(capacity=200)
    smriti = SmritiCache(cache_dir=runtime_dir / "Cache")

    agni = Agni(
        runtime_root=runtime_dir,
        output_root=output_dir,
        darpana=darpana,
        smriti=smriti,
    )

    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("Hello from Smriti verified cache pipeline!", encoding="utf-8")

    inp = InputRef(
        input_id="inp-smriti-1",
        source_path=sample_file,
        display_name="sample.txt",
        size_bytes=sample_file.stat().st_size,
    )

    req = Request(
        request_id="req-smriti-1",
        requirement="read_native",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
    )

    ctx1 = ExecutionContext("run-1", "req-smriti-1", "t-1", "s-1")
    res1 = agni.execute(req, context=ctx1)
    assert isinstance(res1, Result)
    assert isinstance(res1.data, CanonicalDocument)
    assert res1.data.text == "Hello from Smriti verified cache pipeline!"

    recs1 = [r for r in darpana.maruti_records() if r.run_id == "run-1" and r.phase_name == "cache.lookup"]
    assert len(recs1) >= 1
    miss_rec = recs1[0]
    assert miss_rec.attributes["outcome"] == "miss"
    assert "cache_tier" not in miss_rec.attributes

    ctx2 = ExecutionContext("run-2", "req-smriti-1", "t-2", "s-2")
    res2 = agni.execute(req, context=ctx2)
    assert isinstance(res2, Result)

    recs2 = [r for r in darpana.maruti_records() if r.run_id == "run-2" and r.phase_name == "cache.lookup"]
    assert len(recs2) >= 1
    assert recs2[0].attributes["outcome"] == "hit"
    assert recs2[0].attributes["cache_tier"] == "l1"

    smriti._l1.invalidate()
    ctx3 = ExecutionContext("run-3", "req-smriti-1", "t-3", "s-3")
    res3 = agni.execute(req, context=ctx3)
    assert isinstance(res3, Result)

    recs3 = [r for r in darpana.maruti_records() if r.run_id == "run-3" and r.phase_name == "cache.lookup"]
    assert len(recs3) >= 1
    assert recs3[0].attributes["outcome"] == "hit"
    assert recs3[0].attributes["cache_tier"] == "l2"


def test_retry_success_populates_smriti_cache(tmp_path: Path) -> None:
    from sarathi.dosh import DoshError, FailureCode
    from sarathi.nabhi.kosh import Kosh
    from sarathi.nabhi.manthan import CapabilityPlan, Manthan
    from sarathi.nabhi.pravaha import Pravaha
    from sarathi.nabhi.quarantine import QuarantineStore, RetryPolicy
    from sarathi.sankalpa import CapabilityDeclaration, DeviceType, PluginInfo, SecurityDeclaration
    from sarathi.yantra import DeviceInfo, DeviceInventory, Yantra

    cache = SmritiCache(cache_dir=tmp_path / "Cache")
    quar_store = QuarantineStore(root=tmp_path / "Quarantine")
    retry_policy = RetryPolicy(max_retries=2, retryable_codes=(FailureCode.EXECUTION_FAILED,))

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
        capabilities={"test_cap": FlakyCapability()},
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

    plan = CapabilityPlan(request_id=req.request_id, capability_ids=("test_cap",))
    ctx = ExecutionContext("run-1", "req-1", "t1", "s1", profile=ExecutionProfile.INSTANT)

    result = pravaha.execute(plan, req, ctx)
    assert result.data.document_id == "doc-recovered"
    assert call_count == 2

    cache_key = compute_cache_key(req, "test_cap", "1.0.0")
    cached_res = cache.get(cache_key)
    assert cached_res is not None
    assert cached_res.data.text == "Recovered text"


def test_smriti_l1_and_l2_cache_equivalence(tmp_path: Path) -> None:
    from sarathi.sankalpa import ArtifactIntent, ArtifactPayload, PageData, TextSpan
    from sarathi.smriti.key import CacheKey

    cache = SmritiCache(cache_dir=tmp_path)
    span = TextSpan(text="Heading", confidence=0.99, bounding_box=(0.0, 0.0, 50.0, 10.0))
    intent = ArtifactIntent(
        name="report.pdf",
        role="export",
        media_type="application/pdf",
        relative_path=Path("exports/report.pdf"),
    )
    payload = ArtifactPayload(intent=intent, content=b"%PDF-1.4")
    doc = CanonicalDocument(
        document_id="d1",
        source_input_id="i1",
        text="Heading",
        pages=(PageData(page_number=1, text="Heading", spans=(span,)),),
    )
    original_result = Result(data=doc, artifact_payloads=(payload,))

    key = CacheKey(key_hash="test_key_equivalence_123", capability_id="ocr", fingerprint="fp123", profile="instant")
    cache.put(key, original_result)

    l1_hit = cache.get(key)
    assert l1_hit is not None
    assert l1_hit.data.pages[0].spans[0].text == "Heading"

    cache._l1.invalidate(key=key)
    assert cache._l1.get(key) is None

    l2_hit = cache.get(key)
    assert l2_hit is not None
    assert isinstance(l2_hit.data, CanonicalDocument)
    assert len(l2_hit.data.pages[0].spans) == 1
    assert l2_hit.data.pages[0].spans[0].text == "Heading"
    assert l2_hit.data.pages[0].spans[0].bounding_box == (0.0, 0.0, 50.0, 10.0)


def test_sqlite_store_bounded_eviction_and_connection_reuse(tmp_path: Path) -> None:
    from sarathi.smriti.key import CacheKey
    from sarathi.smriti.policy import CachePolicy
    from sarathi.smriti.store import SQLiteCacheStore

    policy = CachePolicy(max_entries_l2=10)
    store = SQLiteCacheStore(db_path=tmp_path / "cache.db", policy=policy)

    conn1 = store._get_connection()
    conn2 = store._get_connection()
    assert conn1 is conn2

    doc = CanonicalDocument(document_id="d1", source_input_id="i1", text="test")
    res = Result(data=doc)

    for idx in range(15):
        k = CacheKey(
            capability_id="test",
            fingerprint=f"fp_{idx}",
            profile="fast",
            key_hash=f"hash_{idx:04d}",
        )
        store.put(k, res)

    with store._lock, store._get_connection() as conn:
        keys = [
            row[0] for row in conn.execute("SELECT key_hash FROM smriti_entries ORDER BY accessed_at ASC").fetchall()
        ]

    assert keys == [f"hash_{idx:04d}" for idx in range(5, 15)]

    retained = set(keys)
    refresh_key = CacheKey(
        capability_id="test",
        fingerprint="fp_10",
        profile="fast",
        key_hash="hash_0010",
    )
    store.put(
        refresh_key,
        Result(data=CanonicalDocument(document_id="d2", source_input_id="i1", text="refreshed")),
    )
    with store._lock, store._get_connection() as conn:
        refreshed_keys = {row[0] for row in conn.execute("SELECT key_hash FROM smriti_entries").fetchall()}

    assert refreshed_keys == retained
    refreshed = store.get(refresh_key)
    assert refreshed is not None
    assert refreshed.data.text == "refreshed"
    store.close()


def test_sqlite_store_evicts_entry_on_corrupt_artifact_blob(tmp_path: Path) -> None:
    """Verify SQLiteCacheStore treats corrupt or missing artifact blobs as cache misses and evicts the entry."""
    from sarathi.sankalpa import ArtifactIntent, ArtifactPayload
    from sarathi.smriti.key import CacheKey
    from sarathi.smriti.store import SQLiteCacheStore

    store = SQLiteCacheStore(db_path=tmp_path / "cache.db")
    doc = CanonicalDocument(document_id="doc_blob", text="Blob test")
    large_bytes = b"sample_blob_content" * 2000
    payload = ArtifactPayload(
        intent=ArtifactIntent(name="data.bin", role="raw_data", media_type="application/octet-stream"),
        content=large_bytes,
    )
    result = Result(data=doc, artifact_payloads=(payload,))
    key = CacheKey(capability_id="test", fingerprint="fp_blob", profile="instant", key_hash="blob_hash_001")
    store.put(key, result)

    # Corrupt the artifact .bin file on disk
    artifacts_dir = tmp_path / "artifacts"
    bin_files = list(artifacts_dir.glob("*.bin"))
    assert len(bin_files) == 1
    bin_files[0].write_bytes(b"corrupted")

    # Store get should catch the corruption, delete the invalid entry, and return None (cache miss)
    miss_result = store.get(key)
    assert miss_result is None

    # Entry is deleted from SQLite
    with store._lock, store._get_connection() as conn:
        row = conn.execute("SELECT 1 FROM smriti_entries WHERE key_hash = ?", (key.key_hash,)).fetchone()
        assert row is None
    store.close()


def test_sqlite_cache_store_reclaims_unreferenced_artifact_blobs(tmp_path: Path) -> None:
    """Verify SQLiteCacheStore deletes orphaned .bin artifact blobs when cache entries are invalidated."""
    from sarathi.sankalpa import ArtifactIntent, ArtifactPayload, CanonicalDocument, Result
    from sarathi.smriti.key import CacheKey
    from sarathi.smriti.store import SQLiteCacheStore

    store = SQLiteCacheStore(db_path=tmp_path / "cache_reclaim.db")
    doc = CanonicalDocument(document_id="doc_reclaim", text="Artifact cleanup test")
    large_bytes = b"large_blob_payload_to_trigger_out_of_band_storage" * 500
    payload = ArtifactPayload(
        intent=ArtifactIntent(name="output.bin", role="document_export", media_type="application/octet-stream"),
        content=large_bytes,
    )
    result = Result(data=doc, artifact_payloads=(payload,))
    key = CacheKey(capability_id="test", fingerprint="fp_reclaim", profile="instant", key_hash="reclaim_hash_001")

    store.put(key, result)

    artifacts_dir = tmp_path / "artifacts"
    bin_files = list(artifacts_dir.glob("*.bin"))
    assert len(bin_files) == 1, "Artifact blob must be saved to artifacts dir"

    # Invalidate the cache entry
    store.invalidate(key)

    # Blob must be reclaimed because no entries reference it
    bin_files_after = list(artifacts_dir.glob("*.bin"))
    assert len(bin_files_after) == 0, "Orphaned artifact blob must be unlinked"
    store.close()
