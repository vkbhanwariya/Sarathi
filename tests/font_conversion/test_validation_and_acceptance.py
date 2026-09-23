"""Tests for Mapping Coverage, Residual Legacy Glyph Detection, and Devanagari Structural Validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, PageData, Request, Result, TextSpan
from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.detector import load_font_profiles
from sarathi.shakti.font_conversion.validator import (
    calculate_mapping_coverage,
    validate_devanagari_structure,
)


def test_calculate_mapping_coverage() -> None:
    """Verify mapping coverage correctly measures mapped vs unmapped character tokens."""
    profiles = load_font_profiles()
    kruti = profiles["krutidev010"]

    # Fully mapped legacy text: "Hkkjr ljdkj"
    full_metrics = calculate_mapping_coverage("Hkkjr ljdkj", kruti)
    assert full_metrics.mapping_coverage > 0.95
    assert full_metrics.unmapped_tokens == 0

    # Unmapped foreign tokens mixed in: e.g. Chinese characters
    mixed_metrics = calculate_mapping_coverage("Hkkjr 漢字", kruti)
    assert mixed_metrics.mapping_coverage < 0.95
    assert mixed_metrics.unmapped_tokens > 0


@pytest.mark.parametrize(
    ("sample_text", "expected_defect"),
    [
        ("्क", "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY"),
        ("क् ा", "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY"),
        ("काा", "CONSECUTIVE_DEPENDENT_MATRAS"),
        ("केै", "CONSECUTIVE_DEPENDENT_MATRAS"),
        ("ाक", "ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY"),
        ("भारत ñ सरकार", "RESIDUAL_LEGACY_GLYPHS"),
    ],
)
def test_devanagari_structural_defects_detected(sample_text: str, expected_defect: str) -> None:
    """Verify validator detects structural defects and residual legacy glyphs."""
    valid, defects = validate_devanagari_structure(sample_text)
    assert not valid
    assert any(expected_defect in d for d in defects)


def test_structural_defect_emits_warning_and_completes_in_capability() -> None:
    """Verify capability completes conversion and emits classified warning when converted text has structural defects."""
    cap = FontConversionCapability()

    # Legacy text with valid KrutiDev signature 'Hk' plus consecutive double matras 'dkk' -> 'काा'
    defect_legacy_text = "Hkkjr dkk"
    doc = CanonicalDocument(
        document_id="doc-defect",
        source_input_id="inp-defect",
        text=defect_legacy_text,
    )
    req = Request(
        request_id="req-defect",
        requirement="font_conversion",
        inputs=(InputRef("inp-defect", Path("sample.txt"), "sample.txt", 10),),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-def", "req-def", "t-def", "s-def")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res, Result)
    assert len(res.artifact_payloads) == 2
    assert any(w.code == "DEVANAGARI_STRUCTURAL_DEFECT" for w in res.warnings)
    defect_warn = next(w for w in res.warnings if w.code == "DEVANAGARI_STRUCTURAL_DEFECT")
    assert "structural Devanagari defect" in defect_warn.message


def test_cross_run_split_matra_does_not_fail_structural_validation() -> None:
    """Verify cross-run split syllables (e.g. 'd' in span 1, 'k' in span 2) convert cleanly without orphan matra error."""
    cap = FontConversionCapability()

    s1 = TextSpan(text="d", metadata={"font_name": "Kruti Dev 010"})
    s2 = TextSpan(text="k", metadata={"font_name": "Kruti Dev 010"})
    page = PageData(page_number=1, text="dk", spans=(s1, s2))
    doc = CanonicalDocument(
        document_id="doc-split",
        source_input_id="inp-split",
        pages=(page,),
        text="dk",
    )
    req = Request(
        request_id="req-split",
        requirement="font_conversion",
        inputs=(InputRef("inp-split", Path("split.txt"), "split.txt", 10),),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-split", "req-split", "t-split", "s-split")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res, Result)
    converted: CanonicalDocument = res.data
    assert converted.text == "का"
    assert len(res.artifact_payloads) == 2


def test_batch_font_conversion_with_structural_defect_completes_with_warnings() -> None:
    """Verify that a batch with 1 valid document and 1 document with structural defects completes and emits warning."""
    cap = FontConversionCapability()

    valid_doc = CanonicalDocument(
        document_id="doc-valid",
        source_input_id="inp-valid",
        text="Hkkjr ljdkj",
    )
    defect_doc = CanonicalDocument(
        document_id="doc-defect",
        source_input_id="inp-defect",
        text="Hkkjr dkk",
    )
    req = Request(
        request_id="req-batch",
        requirement="font_conversion",
        inputs=(
            InputRef("inp-valid", Path("valid.txt"), "valid.txt", 20),
            InputRef("inp-defect", Path("defect.txt"), "defect.txt", 20),
        ),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-batch", "req-batch", "t-batch", "s-batch")

    res = cap.execute(req, ctx, prior_result=Result(data=(valid_doc, defect_doc)))
    assert isinstance(res, Result)
    assert isinstance(res.data, tuple)
    assert len(res.data) == 2

    # Both docs converted and artifacts produced
    assert "भारत सरकार" in res.data[0].text
    assert len(res.artifact_payloads) == 4

    # Warning exists on result page for the defective document
    assert any(w.code == "DEVANAGARI_STRUCTURAL_DEFECT" for w in res.warnings)


def test_batch_font_conversion_item_scoped_fault_tolerance_on_dosh_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that if one document raises DoshError in a batch, valid documents succeed and failed doc is quarantined with warning."""
    cap = FontConversionCapability()

    doc1 = CanonicalDocument(
        document_id="doc-1",
        source_input_id="inp-1",
        text="Hkkjr ljdkj",
    )
    doc2 = CanonicalDocument(
        document_id="doc-2",
        source_input_id="inp-2",
        text="Hkkjr ljdkj",
    )
    req = Request(
        request_id="req-b-err",
        requirement="font_conversion",
        inputs=(
            InputRef("inp-1", Path("1.txt"), "1.txt", 20),
            InputRef("inp-2", Path("2.txt"), "2.txt", 20),
        ),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-be", "req-b-err", "t-be", "s-be")

    call_count = 0
    orig_conv = cap._converter.convert

    def mock_convert(text: str, profile_id: str | None = None):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise DoshError(FailureCode.EXECUTION_FAILED, "Hardware decoder fault.")
        return orig_conv(text, profile_id=profile_id)

    monkeypatch.setattr(cap._converter, "convert", mock_convert)

    res = cap.execute(req, ctx, prior_result=Result(data=(doc1, doc2)))
    assert isinstance(res, Result)
    assert len(res.data) == 2
    # Doc 1 converted
    assert "भारत सरकार" in res.data[0].text
    # Doc 2 marked failed in metadata
    assert res.data[1].metadata.get("conversion_status") == "failed"
    # Artifacts exist only for doc 1
    art_names = {p.intent.name for p in res.artifact_payloads}
    assert "1_converted.txt" in art_names
    assert "2_converted.txt" not in art_names
    # Warning recorded
    assert any(w.code == "FONT_CONVERSION_EXECUTION_FAILED" for w in res.warnings)


def test_batch_font_conversion_all_failing_raises_dosh_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that a batch where all documents raise DoshError raises DoshError."""
    cap = FontConversionCapability()

    doc1 = CanonicalDocument(document_id="doc-1", source_input_id="inp-1", text="Hkkjr ljdkj")
    doc2 = CanonicalDocument(document_id="doc-2", source_input_id="inp-2", text="Hkkjr ljdkj")
    req = Request(
        request_id="req-all-fail",
        requirement="font_conversion",
        inputs=(
            InputRef("inp-1", Path("1.txt"), "1.txt", 20),
            InputRef("inp-2", Path("2.txt"), "2.txt", 20),
        ),
        metadata={"font": "krutidev010"},
    )
    ctx = ExecutionContext("run-af", "req-all-fail", "t-af", "s-af")

    def mock_fail(*args, **kwargs):
        raise DoshError(FailureCode.EXECUTION_FAILED, "Total failure.")

    monkeypatch.setattr(cap._converter, "convert", mock_fail)

    with pytest.raises(DoshError) as exc_info:
        cap.execute(req, ctx, prior_result=Result(data=(doc1, doc2)))

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "Total failure" in exc_info.value.message


def test_unsupported_encoding_returns_original_document_safely() -> None:
    """Verify text without legacy font indicators is preserved safely without corruption."""
    doc = CanonicalDocument(
        document_id="doc-plain",
        text="This is a purely English document without any legacy Devanagari encodings.",
    )
    cap = FontConversionCapability()
    req = Request(
        request_id="req-plain",
        requirement="font_conversion",
        inputs=(InputRef("i1", Path("plain.txt"), "plain.txt", 100),),
    )
    ctx = ExecutionContext("run-plain", "req-plain", "t1", "s1")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res.data, CanonicalDocument)
    assert res.data.text == doc.text
    assert any(w.code == "NO_LEGACY_FONT_DETECTED" for w in res.warnings)


def test_mixed_unicode_and_krutidev_auto_conversion() -> None:
    """Verify document containing mixed Unicode Hindi, English, and KrutiDev converts only legacy text."""
    # "भारतीय संविधान Article 21 Hkkjr ljdkj"
    mixed_text = "भारतीय संविधान Article 21 Hkkjr ljdkj"
    doc = CanonicalDocument(
        document_id="doc-mixed",
        text=mixed_text,
    )
    cap = FontConversionCapability()
    req = Request(
        request_id="req-mixed",
        requirement="font_conversion",
        inputs=(InputRef("i1", Path("mixed.txt"), "mixed.txt", 100),),
    )
    ctx = ExecutionContext("run-mixed", "req-mixed", "t1", "s1")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res.data, CanonicalDocument)

    # Unicode parts remain intact
    assert "भारतीय संविधान" in res.data.text
    assert "Article 21" in res.data.text

    # KrutiDev part converted to Unicode "भारत सरकार"
    assert "भारत सरकार" in res.data.text
    assert "Hkkjr" not in res.data.text


def test_font_conversion_preserves_converted_docx_bytes_in_metadata(tmp_path: Path) -> None:
    """Verify font_conversion attaches converted_docx_bytes to result document metadata."""
    cap = FontConversionCapability()
    doc = CanonicalDocument(
        document_id="doc-docx-continuity",
        text="Hkkjr ljdkj",
    )
    req = Request(
        request_id="req-docx-cont",
        requirement="font_conversion",
        inputs=(InputRef("i1", Path("doc.docx"), "doc.docx", 100),),
    )
    ctx = ExecutionContext("run-cont", "req-cont", "t1", "s1")

    res = cap.execute(req, ctx, prior_result=Result(data=doc))
    assert isinstance(res.data, CanonicalDocument)
    assert "converted_docx_bytes" in res.data.metadata
    assert isinstance(res.data.metadata["converted_docx_bytes"], bytes)
    assert len(res.data.metadata["converted_docx_bytes"]) > 0
