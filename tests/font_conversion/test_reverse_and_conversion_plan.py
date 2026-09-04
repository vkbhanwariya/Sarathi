"""Tests for Reverse Transducers, ConversionPlan Invariants, Batch Escalation, and Source Matching."""

from __future__ import annotations

from pathlib import Path

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.converter import FontConverter


def test_reverse_conversion_prefers_deterministic_reverse_mappings() -> None:
    """Verify Unicode -> legacy uses profile.reverse_preferred for conjuncts."""
    converter = FontConverter()
    # In KrutiDev: 'त्र' -> '=', 'श्र' -> 'J', 'क्ष' -> '{', 'ज्ञ' -> 'K', 'ः' -> '%'
    rev_tra = converter.convert_to_legacy("त्र", target_profile_id="krutidev010")
    assert rev_tra == "="

    rev_shra = converter.convert_to_legacy("श्र", target_profile_id="krutidev010")
    assert rev_shra == "J"

    rev_ksha = converter.convert_to_legacy("क्ष", target_profile_id="krutidev010")
    assert rev_ksha == "{"

    rev_visarga = converter.convert_to_legacy("पुनः", target_profile_id="krutidev010")
    assert "%" in rev_visarga


def test_roundtrip_conversion_fidelity() -> None:
    """Verify legacy -> Unicode -> legacy round-trip maintains identity for canonical words."""
    converter = FontConverter()
    legacy_words = ["Hkkjr", "ljdkj", "dk;Z"]
    for w in legacy_words:
        uni = converter.convert(w, profile_id="krutidev010")
        rev = converter.convert_to_legacy(uni, target_profile_id="krutidev010")
        assert rev == w, f"Round-trip mismatch for '{w}': got '{rev}'"


def test_item_scoped_batch_escalation_all_empty() -> None:
    """Verify when ALL documents in batch are empty, capability escalates to OCR."""
    cap = FontConversionCapability()
    doc1 = CanonicalDocument(document_id="doc-1", source_input_id="inp-1", text="")
    doc2 = CanonicalDocument(document_id="doc-2", source_input_id="inp-2", text="")
    prior = Result(data=(doc1, doc2))

    req = Request(
        request_id="req-empty-batch",
        requirement="font_conversion",
        inputs=(
            InputRef("inp-1", Path("f1.txt"), "f1.txt", 0),
            InputRef("inp-2", Path("f2.txt"), "f2.txt", 0),
        ),
    )
    ctx = ExecutionContext("run-e", "req-e", "t-e", "s-e")
    res = cap.execute(req, ctx, prior)

    assert res.next_requirement == "ocr"
    assert res.resume_self is True


def test_item_scoped_batch_escalation_partial_empty() -> None:
    """Verify when one document is empty and another has content, empty doc is preserved with warning."""
    cap = FontConversionCapability()
    doc_empty = CanonicalDocument(document_id="doc-empty", source_input_id="inp-1", text="")
    doc_content = CanonicalDocument(
        document_id="doc-content",
        source_input_id="inp-2",
        text="Hkkjr ljdkj",
    )
    prior = Result(data=(doc_empty, doc_content))

    req = Request(
        request_id="req-part-empty",
        requirement="font_conversion",
        inputs=(
            InputRef("inp-1", Path("empty.txt"), "empty.txt", 0),
            InputRef("inp-2", Path("content.txt"), "content.txt", 11),
        ),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-p", "req-p", "t-p", "s-p")
    res = cap.execute(req, ctx, prior)

    # Must NOT escalate entire batch to OCR because doc-content has valid content!
    assert res.next_requirement is None
    assert isinstance(res.data, tuple)
    assert len(res.data) == 2

    # doc 1 remains empty and warning is recorded
    assert res.data[0].text == ""
    assert any(w.code == "EMPTY_DOCUMENT_SKIPPED" for w in res.warnings)

    # doc 2 is converted
    assert "भारत सरकार" in res.data[1].text


def test_strict_source_input_id_matching_no_positional_fallback(tmp_path: Path) -> None:
    """Verify capability uses strict source_input_id and does NOT fall back to positional index."""
    cap = FontConversionCapability()

    # Create dummy docx file on disk
    docx_file = tmp_path / "valid.docx"
    docx_file.write_bytes(b"PK\x03\x04dummy")

    doc = CanonicalDocument(
        document_id="doc-orphan",
        source_input_id="inp-mismatched-id",  # ID does NOT match input ref!
        text="Hkkjr",
    )
    inp = InputRef("inp-actual-id", docx_file, "valid.docx", docx_file.stat().st_size)

    req = Request(
        request_id="req-src",
        requirement="font_conversion",
        inputs=(inp,),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-s", "req-s", "t-s", "s-s")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert res.data is not None
    # Because source_input_id did not match inp-actual-id, transform_docx_artifact was NOT invoked on inp,
    # and instead doc was converted as standard CanonicalDocument payload
    assert len(res.artifact_payloads) == 2  # txt payload + synthesized docx payload
