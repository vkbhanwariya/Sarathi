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


def serialize_result(result: Result) -> str:
    """Serialize canonical Result dataclass into deterministic JSON string."""
    data_dict: dict[str, Any] | None = None
    if isinstance(result.data, CanonicalDocument):
        doc = result.data
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
            "capability_id": pr.capability_id,
            "stage": pr.stage,
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
        "metadata": dict(result.metadata),
    }
    return json.dumps(raw, indent=None, sort_keys=True)


def deserialize_result(json_str: str) -> Result:
    """Deserialize JSON string back into canonical Result dataclass."""
    raw = json.loads(json_str)

    data_obj: Any = None
    if raw.get("data") and raw["data"].get("_type") == "CanonicalDocument":
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

        tables = [
            TableData(
                name=t["name"],
                headers=tuple(t["headers"]),
                rows=tuple(tuple(r) for r in t["rows"]),
                metadata=MappingProxyType(t.get("metadata", {})),
            )
            for t in d.get("tables", [])
        ]

        data_obj = CanonicalDocument(
            document_id=d.get("document_id", "doc-cached"),
            source_input_id=d.get("source_input_id", "inp-cached"),
            text=d.get("text", ""),
            pages=tuple(pages),
            tables=tuple(tables),
            detected_type=d.get("detected_type", "document"),
            metadata=MappingProxyType(d.get("metadata", {})),
        )

    payloads = []
    for pl in raw.get("artifact_payloads", []):
        intent_raw = pl["intent"]
        intent = ArtifactIntent(
            name=intent_raw["name"],
            role=intent_raw["role"],
            media_type=intent_raw["media_type"],
            metadata=MappingProxyType(intent_raw.get("metadata", {})),
        )
        content = base64.b64decode(pl["content_b64"].encode("ascii"))
        payloads.append(ArtifactPayload(intent=intent, content=content))

    provs = [
        ProvenanceRecord(
            source_input_id=pr.get("source_input_id"),
            capability_id=pr.get("capability_id", "cached"),
            stage=pr.get("stage", "cached"),
            evidence=MappingProxyType(pr.get("evidence", {})),
            timestamp_utc=pr.get("timestamp_utc"),
        )
        for pr in raw.get("provenance", [])
    ]

    warns = [
        WarningRecord(
            code=w["code"],
            message=w["message"],
            stage=w.get("stage", "cached"),
            context=MappingProxyType(w.get("context", {})),
        )
        for w in raw.get("warnings", [])
    ]

    conf: ConfidenceValue | None = None
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
        metadata=MappingProxyType(raw.get("metadata", {})),
    )
