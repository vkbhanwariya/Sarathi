"""Tests for Contract 2: Canonical Result Serialization and Deserialization."""

from types import MappingProxyType

from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ConfidenceValue,
    PageData,
    ProvenanceRecord,
    Result,
    TableData,
    WarningRecord,
)
from sarathi.smriti.serialization import deserialize_result, serialize_result


def test_round_trip_result_serialization() -> None:
    table = TableData(
        name="Table1",
        headers=("Col1", "Col2"),
        rows=(("Val1", "Val2"), ("Val3", "Val4")),
    )
    page = PageData(page_number=1, text="Page 1 Text", tables=(table,))
    doc = CanonicalDocument(
        document_id="doc-123",
        source_input_id="inp-123",
        text="Full Document Text",
        pages=(page,),
        tables=(table,),
        detected_type="financial_statement",
    )
    payload = ArtifactPayload(
        intent=ArtifactIntent(name="output.txt", role="text", media_type="text/plain"),
        content=b"Sample content bytes",
    )
    prov = ProvenanceRecord(
        source_input_id="inp-123",
        capability_id="read_native",
        stage="extraction",
        evidence=MappingProxyType({"char_count": 18}),
    )
    warn = WarningRecord(
        code="TEST_WARN",
        message="Test warning message",
        stage="extraction",
    )
    conf = ConfidenceValue(
        score=0.98,
        method="extraction_density",
        evidence=MappingProxyType({"density": 0.98}),
    )

    orig_result = Result(
        data=doc,
        artifact_payloads=(payload,),
        confidence=conf,
        warnings=(warn,),
        provenance=(prov,),
        next_requirement=None,
    )

    json_str = serialize_result(orig_result)
    assert isinstance(json_str, str)

    restored = deserialize_result(json_str)

    assert isinstance(restored.data, CanonicalDocument)
    assert restored.data.document_id == "doc-123"
    assert restored.data.text == "Full Document Text"
    assert len(restored.data.pages) == 1
    assert restored.data.pages[0].tables[0].headers == ("Col1", "Col2")
    assert restored.data.pages[0].tables[0].rows == (("Val1", "Val2"), ("Val3", "Val4"))
    assert len(restored.artifact_payloads) == 1
    assert restored.artifact_payloads[0].content == b"Sample content bytes"
    assert restored.artifact_payloads[0].intent.name == "output.txt"
    assert restored.confidence is not None
    assert restored.confidence.score == 0.98
    assert len(restored.provenance) == 1
    assert restored.provenance[0].capability_id == "read_native"
    assert len(restored.warnings) == 1
    assert restored.warnings[0].code == "TEST_WARN"
