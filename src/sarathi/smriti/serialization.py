"""Contract 2: Serializable Canonical Result and Artifact Contract."""

from __future__ import annotations

import base64
import datetime
import json
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ConfidenceValue,
    PageData,
    ProvenanceRecord,
    Result,
    TableData,
    TextSpan,
    WarningRecord,
)


def _serialize_metadata_value(v: Any) -> Any:
    """Losslessly encode metadata values into JSON-compatible tagged representations."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Path):
        return {"__stype__": "Path", "val": str(v)}
    if isinstance(v, datetime.datetime):
        return {"__stype__": "datetime", "val": v.isoformat()}
    if isinstance(v, datetime.date):
        return {"__stype__": "date", "val": v.isoformat()}
    if isinstance(v, datetime.time):
        return {"__stype__": "time", "val": v.isoformat()}
    if isinstance(v, Decimal):
        return {"__stype__": "Decimal", "val": str(v)}
    if isinstance(v, set):
        return {"__stype__": "set", "val": [_serialize_metadata_value(x) for x in sorted(v, key=str)]}
    if isinstance(v, tuple):
        return {"__stype__": "tuple", "val": [_serialize_metadata_value(x) for x in v]}
    if isinstance(v, list):
        return [_serialize_metadata_value(x) for x in v]
    if isinstance(v, Mapping):
        return {str(k): _serialize_metadata_value(val) for k, val in v.items()}
    raise ValueError(f"Unsupported metadata value type '{type(v).__name__}'; cannot be cached losslessly.")


def _deserialize_metadata_value(v: Any) -> Any:
    """Decode tagged representations back into exact canonical objects."""
    if isinstance(v, dict):
        if "__stype__" in v and "val" in v:
            tag = v["__stype__"]
            raw_val = v["val"]
            if tag == "Path":
                return Path(raw_val)
            if tag == "datetime":
                return datetime.datetime.fromisoformat(raw_val)
            if tag == "date":
                return datetime.date.fromisoformat(raw_val)
            if tag == "time":
                return datetime.time.fromisoformat(raw_val)
            if tag == "Decimal":
                return Decimal(raw_val)
            if tag == "set":
                return set(_deserialize_metadata_value(x) for x in raw_val)
            if tag == "tuple":
                return tuple(_deserialize_metadata_value(x) for x in raw_val)
        return {k: _deserialize_metadata_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_deserialize_metadata_value(x) for x in v]
    return v


def _serialize_metadata(meta: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize metadata mapping losslessly, preserving complete canonical types."""
    if not isinstance(meta, Mapping):
        raise ValueError(f"Metadata must be a Mapping, got {type(meta).__name__}")
    return {str(k): _serialize_metadata_value(v) for k, v in meta.items()}


def _deserialize_metadata(meta_dict: Mapping[str, Any] | None) -> dict[str, Any]:
    """Deserialize metadata mapping, restoring tagged types to exact canonical classes."""
    if not isinstance(meta_dict, Mapping):
        return {}
    return {str(k): _deserialize_metadata_value(v) for k, v in meta_dict.items()}


def _serialize_canonical_doc(doc: CanonicalDocument) -> dict[str, Any]:
    """Serialize a single CanonicalDocument."""
    return {
        "_type": "CanonicalDocument",
        "document_id": doc.document_id,
        "source_input_id": doc.source_input_id,
        "text": doc.text,
        "detected_type": doc.detected_type,
        "metadata": _serialize_metadata(doc.metadata),
        "pages": [
            {
                "page_number": p.page_number,
                "text": p.text,
                "metadata": _serialize_metadata(p.metadata),
                "spans": [
                    {
                        "text": s.text,
                        "confidence": s.confidence,
                        "bounding_box": list(s.bounding_box) if s.bounding_box is not None else None,
                        "language": s.language,
                        "script": s.script,
                        "metadata": _serialize_metadata(s.metadata),
                    }
                    for s in p.spans
                ],
                "tables": [
                    {
                        "name": t.name,
                        "headers": list(t.headers),
                        "rows": [list(r) for r in t.rows],
                        "metadata": _serialize_metadata(t.metadata),
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
                "metadata": _serialize_metadata(t.metadata),
            }
            for t in doc.tables
        ],
    }


def _validate_doc_metadata(doc: CanonicalDocument) -> None:
    _serialize_metadata(doc.metadata)
    for p in doc.pages:
        _serialize_metadata(p.metadata)
        for s in p.spans:
            _serialize_metadata(s.metadata)
        for t in p.tables:
            _serialize_metadata(t.metadata)
    for t in doc.tables:
        _serialize_metadata(t.metadata)


def _deserialize_canonical_doc(d: dict[str, Any]) -> CanonicalDocument:
    """Deserialize a single CanonicalDocument dictionary."""
    pages = []
    for p in d.get("pages", []):
        p_spans = [
            TextSpan(
                text=s["text"],
                confidence=s.get("confidence"),
                bounding_box=tuple(s["bounding_box"]) if s.get("bounding_box") is not None else None,
                language=s.get("language"),
                script=s.get("script"),
                metadata=MappingProxyType(_deserialize_metadata(s.get("metadata", {}))),
            )
            for s in p.get("spans", [])
        ]
        p_tables = [
            TableData(
                name=t["name"],
                headers=tuple(t["headers"]),
                rows=tuple(tuple(r) for r in t["rows"]),
                metadata=MappingProxyType(_deserialize_metadata(t.get("metadata", {}))),
            )
            for t in p.get("tables", [])
        ]
        pages.append(
            PageData(
                page_number=p["page_number"],
                text=p["text"],
                spans=tuple(p_spans),
                tables=tuple(p_tables),
                metadata=MappingProxyType(_deserialize_metadata(p.get("metadata", {}))),
            )
        )

    doc_tables = [
        TableData(
            name=t["name"],
            headers=tuple(t["headers"]),
            rows=tuple(tuple(r) for r in t["rows"]),
            metadata=MappingProxyType(_deserialize_metadata(t.get("metadata", {}))),
        )
        for t in d.get("tables", [])
    ]

    return CanonicalDocument(
        document_id=d["document_id"],
        source_input_id=d["source_input_id"],
        text=d["text"],
        detected_type=d.get("detected_type"),
        pages=tuple(pages),
        tables=tuple(doc_tables),
        metadata=MappingProxyType(_deserialize_metadata(d.get("metadata", {}))),
    )


def is_cacheable_result(result: Result) -> bool:
    """Check whether a Result has a supported lossless canonical representation."""
    if not isinstance(result, Result):
        return False
    if result.data is None:
        return False
    if not (
        isinstance(result.data, CanonicalDocument)
        or (
            isinstance(result.data, (tuple, list))
            and len(result.data) > 0
            and all(isinstance(d, CanonicalDocument) for d in result.data)
        )
    ):
        return False

    try:
        if isinstance(result.data, CanonicalDocument):
            _validate_doc_metadata(result.data)
        else:
            for doc in result.data:
                _validate_doc_metadata(doc)
        _serialize_metadata(result.metadata)
        for p in result.artifact_payloads:
            _serialize_metadata(p.intent.metadata)
        for w in result.warnings:
            _serialize_metadata(w.context)
        for pr in result.provenance:
            _serialize_metadata(pr.evidence)
        if result.confidence is not None:
            _serialize_metadata(result.confidence.evidence)
    except (ValueError, TypeError):
        return False

    return True


def serialize_result(result: Result) -> str:
    """Serialize canonical Result dataclass into deterministic JSON string."""
    if not is_cacheable_result(result):
        raise ValueError(f"Result with data of type {type(result.data).__name__} is not cacheable.")

    if isinstance(result.data, CanonicalDocument):
        data_dict: dict[str, Any] = _serialize_canonical_doc(result.data)
    elif isinstance(result.data, (tuple, list)) and all(isinstance(d, CanonicalDocument) for d in result.data):
        data_dict = {
            "_type": "MultiCanonicalDocument",
            "documents": [_serialize_canonical_doc(d) for d in result.data],
        }
    else:
        raise ValueError(f"Result with data of type {type(result.data).__name__} is not cacheable.")

    payloads_list = []
    for p in result.artifact_payloads:
        payloads_list.append(
            {
                "intent": {
                    "name": p.intent.name,
                    "role": p.intent.role,
                    "media_type": p.intent.media_type,
                    "relative_path": str(p.intent.relative_path) if p.intent.relative_path is not None else None,
                    "metadata": _serialize_metadata(p.intent.metadata),
                },
                "content_b64": base64.b64encode(p.content).decode("ascii"),
            }
        )

    provenance_list = [
        {
            "source_input_id": pr.source_input_id,
            "source_file": pr.source_file,
            "stage": pr.stage,
            "plugin_id": pr.plugin_id,
            "capability_id": pr.capability_id,
            "page_number": pr.page_number,
            "region": pr.region,
            "evidence": _serialize_metadata(pr.evidence),
            "timestamp_utc": pr.timestamp_utc,
        }
        for pr in result.provenance
    ]

    warnings_list = [
        {
            "code": w.code,
            "message": w.message,
            "stage": w.stage,
            "context": _serialize_metadata(w.context),
        }
        for w in result.warnings
    ]

    conf_dict: dict[str, Any] | None = None
    if result.confidence is not None:
        conf_dict = {
            "score": result.confidence.score,
            "method": result.confidence.method,
            "evidence": _serialize_metadata(result.confidence.evidence),
        }

    raw = {
        "data": data_dict,
        "artifact_payloads": payloads_list,
        "confidence": conf_dict,
        "warnings": warnings_list,
        "provenance": provenance_list,
        "next_requirement": result.next_requirement,
        "resume_self": result.resume_self,
        "metadata": _serialize_metadata(result.metadata),
    }
    return json.dumps(raw, indent=None, sort_keys=True)


def deserialize_result(json_str: str) -> Result:
    """Deserialize JSON string back into canonical Result dataclass."""
    raw = json.loads(json_str)

    d = raw.get("data")
    if not d or not isinstance(d, dict) or d.get("_type") not in ("CanonicalDocument", "MultiCanonicalDocument"):
        raise ValueError("Invalid serialized cache entry: missing or unsupported CanonicalDocument data.")

    if d["_type"] == "CanonicalDocument":
        data_obj: Any = _deserialize_canonical_doc(d)
    else:
        data_obj = tuple(_deserialize_canonical_doc(doc_d) for doc_d in d.get("documents", []))

    payloads = []
    for p in raw.get("artifact_payloads", []):
        intent_dict = p.get("intent", {})
        rel_path = intent_dict.get("relative_path")
        payloads.append(
            ArtifactPayload(
                intent=ArtifactIntent(
                    name=intent_dict["name"],
                    role=intent_dict["role"],
                    media_type=intent_dict["media_type"],
                    relative_path=Path(rel_path) if rel_path else None,
                    metadata=MappingProxyType(_deserialize_metadata(intent_dict.get("metadata", {}))),
                ),
                content=base64.b64decode(p["content_b64"].encode("ascii")),
            )
        )

    warns = [
        WarningRecord(
            code=w["code"],
            message=w["message"],
            stage=w.get("stage"),
            context=MappingProxyType(_deserialize_metadata(w.get("context", {}))),
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
            evidence=MappingProxyType(_deserialize_metadata(pr.get("evidence", {}))),
            timestamp_utc=pr.get("timestamp_utc"),
        )
        for pr in raw.get("provenance", [])
    ]

    conf = None
    if raw.get("confidence"):
        conf = ConfidenceValue(
            score=raw["confidence"]["score"],
            method=raw["confidence"]["method"],
            evidence=MappingProxyType(_deserialize_metadata(raw["confidence"].get("evidence", {}))),
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
        metadata=MappingProxyType(_deserialize_metadata(raw.get("metadata", {}))),
    )
