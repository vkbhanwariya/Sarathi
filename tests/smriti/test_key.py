"""Tests for Contract 1: Stable Privacy-Safe Cache Key Computation."""

from pathlib import Path

from sarathi.sankalpa import ExecutionProfile, InputRef, Request
from sarathi.smriti.key import compute_cache_key, compute_input_fingerprint


def test_input_fingerprint_deterministic_and_path_agnostic(tmp_path: Path) -> None:
    path_a = tmp_path / "dir_a" / "sample.pdf"
    path_b = tmp_path / "dir_b" / "sample.pdf"

    inp_a = InputRef(
        input_id="inp-1",
        source_path=path_a,
        display_name="sample.pdf",
        size_bytes=1024,
        media_type="application/pdf",
    )
    inp_b = InputRef(
        input_id="inp-1",
        source_path=path_b,
        display_name="sample.pdf",
        size_bytes=1024,
        media_type="application/pdf",
    )

    # Different filesystem paths with same factual metadata must produce identical privacy-safe fingerprint
    fp_a = compute_input_fingerprint((inp_a,))
    fp_b = compute_input_fingerprint((inp_b,))

    assert fp_a == fp_b
    assert str(path_a) not in fp_a
    assert str(path_b) not in fp_b


def test_cache_key_sensitivity_to_profile_and_capability(tmp_path: Path) -> None:
    inp = InputRef(
        input_id="inp-1",
        source_path=tmp_path / "doc.txt",
        display_name="doc.txt",
        size_bytes=500,
    )
    req_instant = Request(
        request_id="req-1",
        requirement="read_native",
        inputs=(inp,),
        profile=ExecutionProfile.INSTANT,
    )
    req_accurate = Request(
        request_id="req-1",
        requirement="read_native",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
    )

    key_instant = compute_cache_key(req_instant, "read_native", "1.0.0")
    key_accurate = compute_cache_key(req_accurate, "read_native", "1.0.0")
    key_other_cap = compute_cache_key(req_instant, "ocr", "1.0.0")

    assert key_instant.key_hash != key_accurate.key_hash
    assert key_instant.key_hash != key_other_cap.key_hash
