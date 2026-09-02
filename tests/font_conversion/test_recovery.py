"""Tests verifying recovery and absence of speculative frameworks in Roopa."""

from pathlib import Path

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result
from sarathi.shakti.font_conversion.capability import FontConversionCapability


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
