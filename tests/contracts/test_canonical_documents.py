"""Tests for canonical document payload normalization."""

from pathlib import Path

from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef, Request, Result
from sarathi.sankalpa.document import normalize_canonical_documents
from sarathi.shakti.darshana.capability import DarshanaCapability


def test_normalize_canonical_documents_supported_shapes() -> None:
    first = CanonicalDocument(document_id="doc-1")
    second = CanonicalDocument(document_id="doc-2")

    assert normalize_canonical_documents(first) == (first,)
    assert normalize_canonical_documents([first, second]) == (first, second)
    assert normalize_canonical_documents((first, second)) == (first, second)
    assert normalize_canonical_documents([]) == ()
    assert normalize_canonical_documents([first, "invalid"]) is None
    assert normalize_canonical_documents("invalid") is None


def test_darshana_preserves_single_prior_document(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("hello", encoding="utf-8")

    prior_doc = CanonicalDocument(document_id="prior-doc", text="existing")
    prior = Result(data=prior_doc)
    request = Request(
        request_id="req-1",
        requirement="identify",
        inputs=(
            InputRef(
                input_id="inp-1",
                source_path=source,
                display_name=source.name,
                size_bytes=source.stat().st_size,
            ),
        ),
    )
    context = ExecutionContext(
        run_id="run-1",
        request_id="req-1",
        trace_id="tr-1",
        span_id="sp-1",
    )

    result = DarshanaCapability().execute(request, context, prior)

    assert isinstance(result.data, tuple)
    assert result.data[0] is prior_doc
    assert len(result.data) == 2
    assert result.data[1].source_input_id == "inp-1"
