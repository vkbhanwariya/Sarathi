"""Focused regression tests for Mistral translation document fidelity."""

from pathlib import Path
from unittest.mock import MagicMock

from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    InputRef,
    PageData,
    Request,
    Result,
    TableData,
    TextSpan,
)
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.translation import MistralTranslationCapability


def test_mistral_translation_preserves_canonical_document_structure() -> None:
    client = MagicMock(spec=MistralClient)
    client.chat_translate.return_value = "translated"

    span = TextSpan(
        text="source span",
        confidence=0.93,
        bounding_box=(1.0, 2.0, 3.0, 4.0),
        metadata={"region": "body"},
    )
    table = TableData(
        name="summary",
        headers=("Field", "Value"),
        rows=(("A", "B"),),
        metadata={"source": "ocr"},
    )
    page = PageData(
        page_number=1,
        text="source page",
        spans=(span,),
        tables=(table,),
        metadata={"confidence": 0.93},
    )
    source = CanonicalDocument(
        document_id="doc-source",
        source_input_id="inp-2",
        text="source document",
        pages=(page,),
        tables=(table,),
        detected_type="ocr_document",
        metadata={"origin": "mistral_ocr"},
    )

    request = Request(
        request_id="req-1",
        requirement="mistral_translation",
        inputs=(
            InputRef("inp-1", Path("first.txt"), "first.txt", 10),
            InputRef("inp-2", Path("second.txt"), "second.txt", 10),
        ),
        metadata={"direction": "hi-en"},
    )
    context = ExecutionContext("run-1", "req-1", "trace-1", "span-1")

    result = MistralTranslationCapability(client=client).execute(
        request,
        context,
        prior_result=Result(data=source),
    )

    assert isinstance(result.data, CanonicalDocument)
    translated = result.data
    assert translated.document_id == "doc-source-translated"
    assert translated.source_input_id == "inp-2"
    assert translated.detected_type == "ocr_document"
    assert translated.tables == (table,)
    assert translated.pages[0].metadata == {"confidence": 0.93}
    assert translated.pages[0].spans == (span,)
    assert translated.pages[0].tables == (table,)
    assert translated.text == "translated"
    assert translated.pages[0].text == "translated"
    assert translated.metadata["origin"] == "mistral_ocr"
    assert translated.metadata["provider"] == "mistral"
    assert translated.metadata["direction"] == "Hindi->English"

    artifact_names = {payload.intent.name for payload in result.artifact_payloads}
    assert any(name.startswith("second_") for name in artifact_names)
