"""Tests for Contract 2: Canonical Result Serialization Safety."""

from dataclasses import dataclass
from pathlib import Path
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
    assert '"stage_name"' not in json_str
    assert '"stage": "extraction"' in json_str

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
    assert restored.artifact_payloads[0].intent.role == "text"

    # Verify provenance contract
    assert len(restored.provenance) == 1
    assert restored.provenance[0].source_input_id == "inp-123"
    assert restored.provenance[0].capability_id == "read_native"
    assert restored.provenance[0].stage == "extraction"
    assert restored.provenance[0].evidence["char_count"] == 18

    # Verify warnings contract
    assert len(restored.warnings) == 1
    assert restored.warnings[0].code == "TEST_WARN"
    assert restored.warnings[0].message == "Test warning message"
    assert restored.warnings[0].stage == "extraction"

    # Verify confidence contract
    assert restored.confidence is not None
    assert restored.confidence.score == pytest.approx(0.98)
    assert restored.confidence.method == "extraction_density"
    assert restored.confidence.evidence["density"] == 0.98


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


def test_sqlite_prunes_corrupted_entry_and_returns_miss(tmp_path: Path) -> None:
    from sarathi.smriti.key import CacheKey
    from sarathi.smriti.store import SQLiteCacheStore

    db_path = tmp_path / "cache" / "test.db"
    store = SQLiteCacheStore(db_path=db_path)
    key = CacheKey("read_native", "test_fp", "instant", "test_hash_1234")

    # Manually insert corrupted data_json
    with store._lock, store._get_connection() as conn:
        conn.execute(
            """
            INSERT INTO smriti_entries
            (key_hash, capability_id, fingerprint, profile, data_json, created_at, accessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (key.key_hash, "read_native", "test_fp", "instant", "{corrupt_json_not_valid", 100.0, 100.0),
        )

    # Retrieval should catch error, prune corrupted entry, and return None (cache miss)
    result = store.get(key)
    assert result is None

    # Entry must be pruned from SQLite
    with store._lock, store._get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM smriti_entries WHERE key_hash = ?", (key.key_hash,)).fetchone()
        assert row[0] == 0
