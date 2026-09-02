"""Tests for Contract 1: Truthful and Privacy-Safe Cache Key Identity."""

from pathlib import Path

from sarathi.sankalpa import CanonicalDocument, ExecutionProfile, InputRef, Request, Result
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

    fp_a = compute_input_fingerprint((inp_a,))
    fp_b = compute_input_fingerprint((inp_b,))

    assert fp_a == fp_b
    assert str(path_a) not in fp_a
    assert str(path_b) not in fp_b


def test_translation_direction_changes_cache_key(tmp_path: Path) -> None:
    inp = InputRef(
        input_id="inp-tr",
        source_path=tmp_path / "text.txt",
        display_name="text.txt",
        size_bytes=200,
    )
    req_hi_en = Request(
        request_id="req-tr-1",
        requirement="translation",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "hi-en"},
    )
    req_en_hi = Request(
        request_id="req-tr-1",
        requirement="translation",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
        metadata={"direction": "en-hi"},
    )

    key_hi_en = compute_cache_key(req_hi_en, "translation", "1.0.0")
    key_en_hi = compute_cache_key(req_en_hi, "translation", "1.0.0")

    assert key_hi_en.key_hash != key_en_hi.key_hash


def test_relevant_custom_options_change_cache_key(tmp_path: Path) -> None:
    inp = InputRef(input_id="inp-1", source_path=tmp_path / "doc.txt", display_name="doc.txt", size_bytes=100)
    req1 = Request(request_id="req-1", requirement="ocr", inputs=(inp,), custom_options={"dpi": 300})
    req2 = Request(request_id="req-1", requirement="ocr", inputs=(inp,), custom_options={"dpi": 150})

    key1 = compute_cache_key(req1, "ocr", "1.0.0")
    key2 = compute_cache_key(req2, "ocr", "1.0.0")

    assert key1.key_hash != key2.key_hash


def test_different_prior_result_changes_downstream_cache_key(tmp_path: Path) -> None:
    inp = InputRef(input_id="inp-1", source_path=tmp_path / "doc.txt", display_name="doc.txt", size_bytes=100)
    req = Request(request_id="req-1", requirement="translation", inputs=(inp,))

    doc_a = CanonicalDocument(document_id="doc-a", source_input_id="inp-1", text="Source A")
    doc_b = CanonicalDocument(document_id="doc-b", source_input_id="inp-1", text="Source B")

    res_a = Result(data=doc_a)
    res_b = Result(data=doc_b)

    key_a = compute_cache_key(req, "translation", "1.0.0", prior_result=res_a)
    key_b = compute_cache_key(req, "translation", "1.0.0", prior_result=res_b)
    key_none = compute_cache_key(req, "translation", "1.0.0", prior_result=None)

    assert key_a.key_hash != key_b.key_hash
    assert key_a.key_hash != key_none.key_hash


def test_identical_canonical_inputs_produce_identical_key(tmp_path: Path) -> None:
    inp1 = InputRef(input_id="inp-1", source_path=tmp_path / "p1.txt", display_name="doc.txt", size_bytes=100)
    inp2 = InputRef(input_id="inp-1", source_path=tmp_path / "p2.txt", display_name="doc.txt", size_bytes=100)

    req1 = Request(request_id="req-1", requirement="read_native", inputs=(inp1,), metadata={"k": "v"})
    req2 = Request(request_id="req-2", requirement="read_native", inputs=(inp2,), metadata={"k": "v"})

    doc = CanonicalDocument(document_id="d1", source_input_id="inp-1", text="Same text")
    res = Result(data=doc)

    key1 = compute_cache_key(req1, "read_native", "1.0.0", prior_result=res)
    key2 = compute_cache_key(req2, "read_native", "1.0.0", prior_result=res)

    assert key1.key_hash == key2.key_hash


def test_page_and_table_content_changes_cache_key(tmp_path: Path) -> None:
    """Documents with identical overall text but different page/table contents produce different keys."""
    from sarathi.sankalpa import PageData, TableData

    inp = InputRef(input_id="inp-1", source_path=tmp_path / "p.txt", display_name="doc.txt", size_bytes=100)
    req = Request(request_id="req-1", requirement="translation", inputs=(inp,))

    # Doc 1: Page with Table A
    t1 = TableData(headers=("Col1", "Col2"), rows=(("val1", "val2"),))
    p1 = PageData(page_number=1, text="Same doc text", tables=(t1,))
    doc1 = CanonicalDocument(document_id="d1", source_input_id="inp-1", text="Same doc text", pages=(p1,))

    # Doc 2: Page with Table B (different cell values)
    t2 = TableData(headers=("Col1", "Col2"), rows=(("diff1", "diff2"),))
    p2 = PageData(page_number=1, text="Same doc text", tables=(t2,))
    doc2 = CanonicalDocument(document_id="d1", source_input_id="inp-1", text="Same doc text", pages=(p2,))

    key1 = compute_cache_key(req, "translation", "1.0.0", prior_result=Result(data=doc1))
    key2 = compute_cache_key(req, "translation", "1.0.0", prior_result=Result(data=doc2))

    assert key1.key_hash != key2.key_hash


def test_non_primitive_options_and_metadata_serialization_safe(tmp_path: Path) -> None:
    """Non-primitive objects (such as Path or custom classes) serialize safely using default=str."""
    inp = InputRef(input_id="inp-1", source_path=tmp_path / "doc.txt", display_name="doc.txt", size_bytes=100)
    req = Request(
        request_id="req-nonprim",
        requirement="ocr",
        inputs=(inp,),
        custom_options={"source_dir": tmp_path / "subdir"},
        metadata={"target_path": tmp_path / "target"},
    )
    # Must not raise TypeError
    key = compute_cache_key(req, "ocr", "1.0.0")
    assert len(key.key_hash) == 64
