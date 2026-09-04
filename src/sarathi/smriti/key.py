"""Contract 1: Stable Privacy-Safe Cache Key Computation for Smriti."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from sarathi.sankalpa import CanonicalDocument, InputRef, Request, Result


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Deterministic, privacy-safe cache key."""

    capability_id: str
    fingerprint: str
    profile: str
    key_hash: str

    def __str__(self) -> str:
        return self.key_hash


def compute_input_fingerprint(inputs: tuple[InputRef, ...]) -> str:
    """Compute a stable, privacy-safe SHA-256 fingerprint from factual input content streamed in request order."""
    hasher = hashlib.sha256()
    hasher.update(f"COUNT:{len(inputs)}:".encode("utf-8"))
    for idx, inp in enumerate(inputs):
        hasher.update(
            f"INP:{idx}:ID:{len(inp.input_id)}:{inp.input_id}:NAME:{len(inp.display_name)}:{inp.display_name}:SIZE:{inp.size_bytes}:TYPE:{inp.media_type or ''}:".encode("utf-8")
        )
        file_read_ok = False
        if inp.source_path and inp.source_path.is_file():
            try:
                with open(inp.source_path, "rb") as f:
                    hasher.update(b":FILE_START:")
                    while chunk := f.read(65536):
                        hasher.update(f"CHUNK:{len(chunk)}:".encode("ascii"))
                        hasher.update(chunk)
                    hasher.update(b":FILE_END:")
                    file_read_ok = True
            except (OSError, PermissionError):
                pass
        if not file_read_ok:
            hasher.update(b":NO_FILE:")
    return hasher.hexdigest()


def _to_digest_serializable(obj: Any) -> Any:
    """Recursively convert objects to JSON-serializable primitives for deterministic digest computation."""
    if obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, (datetime.date, datetime.datetime, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, Mapping):
        return {str(k): _to_digest_serializable(v) for k, v in sorted(obj.items(), key=lambda x: str(x[0]))}
    if isinstance(obj, (set, frozenset)):
        items = [_to_digest_serializable(v) for v in obj]
        return sorted(items, key=lambda x: str(x))
    if isinstance(obj, (list, tuple)):
        return [_to_digest_serializable(v) for v in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_digest_serializable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    return str(obj)


def _hash_canonical_document(doc: CanonicalDocument) -> str:
    """Compute deterministic hash of a CanonicalDocument content, layout, and structure."""
    doc_hasher = hashlib.sha256()
    doc_hasher.update(doc.text.encode("utf-8"))

    for page in doc.pages:
        doc_hasher.update(f":p{page.page_number}:{page.text}:".encode("utf-8"))
        for span in page.spans:
            if span.bounding_box:
                if isinstance(span.bounding_box, (tuple, list)):
                    bb = ",".join(str(c) for c in span.bounding_box)
                else:
                    bb = f"{getattr(span.bounding_box, 'x0', '')},{getattr(span.bounding_box, 'y0', '')},{getattr(span.bounding_box, 'x1', '')},{getattr(span.bounding_box, 'y1', '')}"
            else:
                bb = ""
            sm = f":sm{json.dumps(dict(span.metadata), sort_keys=True, default=str)}:" if span.metadata else ""
            doc_hasher.update(
                f":s{span.text}:{span.confidence}:{bb}:{span.language or ''}:{span.script or ''}{sm}:".encode("utf-8")
            )
        if page.metadata:
            doc_hasher.update(f":pm{json.dumps(dict(page.metadata), sort_keys=True, default=str)}:".encode("utf-8"))
        for tbl in page.tables:
            t_name = tbl.name or ""
            tm = f":tm{json.dumps(dict(tbl.metadata), sort_keys=True, default=str)}:" if tbl.metadata else ""
            doc_hasher.update(f":th{t_name}:{'|'.join(tbl.headers)}{tm}:".encode("utf-8"))
            for row in tbl.rows:
                doc_hasher.update(f":tr{'|'.join(str(c) for c in row)}:".encode("utf-8"))

    for tbl in doc.tables:
        t_name = tbl.name or ""
        tm = f":tm{json.dumps(dict(tbl.metadata), sort_keys=True, default=str)}:" if tbl.metadata else ""
        doc_hasher.update(f":dth{t_name}:{'|'.join(tbl.headers)}{tm}:".encode("utf-8"))
        for row in tbl.rows:
            doc_hasher.update(f":dtr{'|'.join(str(c) for c in row)}:".encode("utf-8"))

    if doc.metadata:
        doc_hasher.update(f":dm{json.dumps(dict(doc.metadata), sort_keys=True, default=str)}:".encode("utf-8"))

    content_hash = doc_hasher.hexdigest()
    return f"{doc.document_id}:{doc.detected_type}:{len(doc.pages)}:{len(doc.tables)}:{content_hash}"


def compute_prior_result_digest(prior_result: Result | None) -> str:
    """Compute a deterministic, privacy-safe digest of upstream prior_result state."""
    if prior_result is None or prior_result.data is None:
        return "none"

    prov_hash = "|".join(f"{p.capability_id}:{p.stage}" for p in prior_result.provenance)

    if isinstance(prior_result.data, CanonicalDocument):
        doc_material = _hash_canonical_document(prior_result.data)
        material = f"{doc_material}:{prov_hash}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    if isinstance(prior_result.data, (tuple, list)) and all(
        isinstance(d, CanonicalDocument) for d in prior_result.data
    ):
        doc_hashes = "|".join(_hash_canonical_document(d) for d in prior_result.data)
        material = f"multi:{len(prior_result.data)}:{doc_hashes}:{prov_hash}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    # Deterministic factual serialization for dataclasses / dicts / sequences / generic types
    try:
        data_serializable = _to_digest_serializable(prior_result.data)
        data_str = json.dumps(data_serializable, sort_keys=True, default=str)
        material = f"{type(prior_result.data).__name__}:{data_str}:{prov_hash}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
    except Exception:
        data_type_name = type(prior_result.data).__name__
        return hashlib.sha256(f"{data_type_name}:{prov_hash}".encode("utf-8")).hexdigest()


def compute_cache_key(
    request: Request,
    capability_id: str,
    plugin_version: str = "1.0.0",
    prior_result: Result | None = None,
    custom_options: Mapping[str, object] | None = None,
) -> CacheKey:
    """Compute canonical deterministic cache key for a capability execution attempt."""
    fingerprint = compute_input_fingerprint(request.inputs)
    options = custom_options if custom_options is not None else request.custom_options
    options_str = json.dumps(dict(options), sort_keys=True, default=str) if options else ""
    metadata_str = json.dumps(dict(request.metadata), sort_keys=True, default=str) if request.metadata else ""
    prior_digest = compute_prior_result_digest(prior_result)

    content = (
        f"{capability_id}:{plugin_version}:{request.profile.value}:"
        f"{fingerprint}:{options_str}:{metadata_str}:{prior_digest}"
    )
    key_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return CacheKey(
        capability_id=capability_id,
        fingerprint=fingerprint,
        profile=request.profile.value,
        key_hash=key_hash,
    )
