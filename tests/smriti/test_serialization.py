"""Tests for Contract 2: Canonical Result Serialization Safety."""

from dataclasses import dataclass
from types import MappingProxyType
import pytest

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
from sarathi.smriti.serialization import (
    deserialize_result,
    is_cacheable_result,
    serialize_result,
)


@dataclass(frozen=True)
class UnsupportedCustomData:
    content: str


def test_canonical_document_round_trips_losslessly() -> None:
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
        detected_type="document",
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

    assert is_cacheable_result(orig_result) is True

    json_str = serialize_result(orig_result)
    restored = deserialize_result(json_str)

    assert isinstance(restored.data, CanonicalDocument)
    assert restored.data.document_id == "doc-123"
    assert restored.data.text == "Full Document Text"
    assert len(restored.data.pages) == 1
    assert restored.data.pages[0].tables[0].headers == ("Col1", "Col2")
    assert restored.data.pages[0].tables[0].rows == (("Val1", "Val2"), ("Val3", "Val4"))
    assert len(restored.artifact_payloads) == 1
    assert restored.artifact_payloads[0].content == b"Sample content bytes"


def test_unsupported_result_data_type_is_not_cacheable() -> None:
    unsupported_res = Result(data=UnsupportedCustomData(content="raw"))
    assert is_cacheable_result(unsupported_res) is False

    with pytest.raises(ValueError) as exc_info:
        serialize_result(unsupported_res)
    assert "not cacheable" in str(exc_info.value)


def test_deserializer_rejects_corrupted_or_none_data() -> None:
    corrupted_json = '{"data": null, "artifact_payloads": []}'
    with pytest.raises(ValueError) as exc_info:
        deserialize_result(corrupted_json)
    assert "missing or unsupported" in str(exc_info.value)
