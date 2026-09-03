"""Contract 1: Stable Privacy-Safe Cache Key Computation for Smriti."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

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
    for inp in inputs:
        # Stream raw content bytes when source file exists
        if inp.source_path and inp.source_path.is_file():
            try:
                with open(inp.source_path, "rb") as f:
                    while chunk := f.read(65536):
                        hasher.update(chunk)
                continue
            except (OSError, PermissionError):
                pass
        # Metadata fallback for virtual/mocked inputs
        hasher.update(f"{inp.input_id}:{inp.display_name}:{inp.size_bytes}:{inp.media_type or ''}".encode("utf-8"))
    return hasher.hexdigest()


def _hash_canonical_document(doc: CanonicalDocument) -> str:
    """Compute deterministic hash of a CanonicalDocument content and structure."""
    doc_hasher = hashlib.sha256()
    doc_hasher.update(doc.text.encode("utf-8"))

    for page in doc.pages:
        doc_hasher.update(f":p{page.page_number}:{page.text}:".encode("utf-8"))
        for span in page.spans:
            doc_hasher.update(f":s{span.text}:{span.confidence}:".encode("utf-8"))
        for tbl in page.tables:
            doc_hasher.update(f":th{'|'.join(tbl.headers)}:".encode("utf-8"))
            for row in tbl.rows:
                doc_hasher.update(f":tr{'|'.join(str(c) for c in row)}:".encode("utf-8"))

    for tbl in doc.tables:
        doc_hasher.update(f":dth{'|'.join(tbl.headers)}:".encode("utf-8"))
        for row in tbl.rows:
            doc_hasher.update(f":dtr{'|'.join(str(c) for c in row)}:".encode("utf-8"))

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

    # Generic factual type representation
    data_type_name = type(prior_result.data).__name__
    return hashlib.sha256(data_type_name.encode("utf-8")).hexdigest()


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
