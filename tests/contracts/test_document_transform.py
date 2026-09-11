"""Focused tests for canonical document transformation semantics."""

import pytest

from sarathi.sankalpa import CanonicalDocument, PageData, TextSpan
from sarathi.sankalpa.document import transform_canonical_document


def test_span_transformer_type_error_propagates() -> None:
    """A transformer bug must not be mistaken for an alternate callback signature."""
    doc = CanonicalDocument(
        document_id="doc-1",
        pages=(PageData(page_number=1, spans=(TextSpan(text="hello"),)),),
    )

    def broken_transform(_: TextSpan) -> str:
        raise TypeError("transformer bug")

    with pytest.raises(TypeError, match="transformer bug"):
        transform_canonical_document(
            doc,
            str.upper,
            detected_type="test",
            span_transform_fn=broken_transform,
        )


def test_default_span_transform_preserves_unmodified_fields() -> None:
    span = TextSpan(
        text="hello",
        confidence=0.9,
        bounding_box=(1.0, 2.0, 3.0, 4.0),
        language="en",
        script="Latn",
        metadata={"source": "ocr"},
    )
    doc = CanonicalDocument(
        document_id="doc-2",
        source_input_id="inp-1",
        pages=(PageData(page_number=1, text="hello", spans=(span,), metadata={"page": 1}),),
        text="hello",
        metadata={"origin": "test"},
    )

    transformed = transform_canonical_document(
        doc,
        str.upper,
        detected_type="translated_document",
        target_lang="hi",
        target_script="Deva",
    )

    out_span = transformed.pages[0].spans[0]
    assert transformed.document_id == doc.document_id
    assert transformed.source_input_id == doc.source_input_id
    assert transformed.metadata == doc.metadata
    assert transformed.text == "HELLO"
    assert transformed.detected_type == "translated_document"
    assert transformed.pages[0].metadata == {"page": 1}
    assert out_span.text == "HELLO"
    assert out_span.confidence == 0.9
    assert out_span.bounding_box == (1.0, 2.0, 3.0, 4.0)
    assert out_span.language == "hi"
    assert out_span.script == "Deva"
    assert out_span.metadata == {"source": "ocr"}
