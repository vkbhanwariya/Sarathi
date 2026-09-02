"""Contract 2: Serializable Canonical Result and Artifact Contract."""

from __future__ import annotations

import base64
import json
from types import MappingProxyType
from typing import Any

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


def is_cacheable_result(result: Result) -> bool:
    """Check whether a Result has a supported lossless canonical representation."""
    if not isinstance(result, Result):
        return False
    if result.data is None:
        return False
    # Only CanonicalDocument is currently supported for lossless canonical serialization
    return isinstance(result.data, CanonicalDocument)


def serialize_result(result: Result) -> str:
    """Serialize canonical Result dataclass into deterministic JSON string."""
    if not is_cacheable_result(result):
        raise ValueError(f"Result with data of type {type(result.data).__name__} is not cacheable.")

    doc = result.data
    assert isinstance(doc, CanonicalDocument)
    data_dict = {
        "_type": "CanonicalDocument",
        "document_id": doc.document_id,
        "source_input_id": doc.source_input_id,
        "text": doc.text,
        "detected_type": doc.detected_type,
        "metadata": dict(doc.metadata),
        "pages": [
            {
                "page_number": p.page_number,
                "text": p.text,
                "metadata": dict(p.metadata),
                "tables": [
                    {
                        "name": t.name,
                        "headers": list(t.headers),
                        "rows": [list(r) for r in t.rows],
                        "metadata": dict(t.metadata),
                    }
                    for t in p.tables
                ],
            }
            for p in doc.pages
        ],
        "tables": [
            {
                "name": t.name,
                "headers": list(t.headers),
                "rows": [list(r) for r in t.rows],
                "metadata": dict(t.metadata),
            }
            for t in doc.tables
        ],
    }

    payloads_list = []
    for p in result.artifact_payloads:
        payloads_list.append({
            "intent": {
                "name": p.intent.name,
                "role": p.intent.role,
                "media_type": p.intent.media_type,
                "metadata": dict(p.intent.metadata),
            },
            "content_b64": base64.b64encode(p.content).decode("ascii"),
        })

    provenance_list = [
        {
            "source_input_id": pr.source_input_id,
            "source_file": pr.source_file,
            "stage": pr.stage,
            "plugin_id": pr.plugin_id,
            "capability_id": pr.capability_id,
            "page_number": pr.page_number,
            "region": pr.region,
            "evidence": dict(pr.evidence),
            "timestamp_utc": pr.timestamp_utc,
        }
        for pr in result.provenance
    ]

    warnings_list = [
        {
            "code": w.code,
            "message": w.message,
            "stage": w.stage,
            "context": dict(w.context),
        }
        for w in result.warnings
    ]

    conf_dict: dict[str, Any] | None = None
    if result.confidence is not None:
        conf_dict = {
            "score": result.confidence.score,
            "method": result.confidence.method,
            "evidence": dict(result.confidence.evidence),
        }

    raw = {
        "data": data_dict,
        "artifact_payloads": payloads_list,
        "confidence": conf_dict,
        "warnings": warnings_list,
        "provenance": provenance_list,
        "next_requirement": result.next_requirement,
        "resume_self": result.resume_self,
        "metadata": dict(result.metadata),
    }
    return json.dumps(raw, indent=None, sort_keys=True)


def deserialize_result(json_str: str) -> Result:
    """Deserialize JSON string back into canonical Result dataclass."""
    raw = json.loads(json_str)

    if not raw.get("data") or raw["data"].get("_type") != "CanonicalDocument":
        raise ValueError("Invalid serialized cache entry: missing or unsupported CanonicalDocument data.")

    d = raw["data"]
    pages = []
    for p in d.get("pages", []):
        p_tables = [
            TableData(
                name=t["name"],
                headers=tuple(t["headers"]),
                rows=tuple(tuple(r) for r in t["rows"]),
                metadata=MappingProxyType(t.get("metadata", {})),
            )
            for t in p.get("tables", [])
        ]
        pages.append(
            PageData(
                page_number=p["page_number"],
                text=p["text"],
                tables=tuple(p_tables),
                metadata=MappingProxyType(p.get("metadata", {})),
            )
        )

    doc_tables = [
        TableData(
            name=t["name"],
            headers=tuple(t["headers"]),
            rows=tuple(tuple(r) for r in t["rows"]),
            metadata=MappingProxyType(t.get("metadata", {})),
        )
        for t in d.get("tables", [])
    ]

    data_obj = CanonicalDocument(
        document_id=d["document_id"],
        source_input_id=d["source_input_id"],
        text=d["text"],
        detected_type=d.get("detected_type"),
        pages=tuple(pages),
        tables=tuple(doc_tables),
        metadata=MappingProxyType(d.get("metadata", {})),
    )

    payloads = [
        ArtifactPayload(
            intent=ArtifactIntent(
                name=p["intent"]["name"],
                role=p["intent"]["role"],
                media_type=p["intent"]["media_type"],
                metadata=MappingProxyType(p["intent"].get("metadata", {})),
            ),
            content=base64.b64decode(p["content_b64"].encode("ascii")),
        )
        for p in raw.get("artifact_payloads", [])
    ]

    warns = [
        WarningRecord(
            code=w["code"],
            message=w["message"],
            stage=w.get("stage"),
            context=MappingProxyType(w.get("context", {})),
        )
        for w in raw.get("warnings", [])
    ]

    provs = [
        ProvenanceRecord(
            source_input_id=pr.get("source_input_id"),
            source_file=pr.get("source_file"),
            stage=pr.get("stage"),
            plugin_id=pr.get("plugin_id"),
            capability_id=pr.get("capability_id"),
            page_number=pr.get("page_number"),
            region=pr.get("region"),
            evidence=MappingProxyType(pr.get("evidence", {})),
            timestamp_utc=pr.get("timestamp_utc"),
        )
        for pr in raw.get("provenance", [])
    ]

    conf = None
    if raw.get("confidence"):
        conf = ConfidenceValue(
            score=raw["confidence"]["score"],
            method=raw["confidence"]["method"],
            evidence=MappingProxyType(raw["confidence"].get("evidence", {})),
        )

    return Result(
        data=data_obj,
        artifact_payloads=tuple(payloads),
        artifacts=(),
        confidence=conf,
        warnings=tuple(warns),
        provenance=tuple(provs),
        next_requirement=raw.get("next_requirement"),
        resume_self=bool(raw.get("resume_self", False)),
        metadata=MappingProxyType(raw.get("metadata", {})),
    )
