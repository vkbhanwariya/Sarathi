"""Tests for Smriti Two-Tier (L1 Memory + L2 SQLite) Cache Service."""

from dataclasses import dataclass
from pathlib import Path

from sarathi.sankalpa import CanonicalDocument, ExecutionProfile, InputRef, Request, Result
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
