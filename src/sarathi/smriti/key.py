"""Contract 1: Stable Privacy-Safe Cache Key Computation for Smriti."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from sarathi.sankalpa import CanonicalDocument, ExecutionProfile, InputRef, Request, Result


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
    """Compute a stable, privacy-safe hash from factual input metadata without filesystem paths."""
    material = "|".join(
        f"{inp.input_id}:{inp.display_name}:{inp.size_bytes}:{inp.media_type or ''}"
        for inp in inputs
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def compute_prior_result_digest(prior_result: Result | None) -> str:
    """Compute a deterministic, privacy-safe digest of upstream prior_result state."""
    if prior_result is None or prior_result.data is None:
        return "none"

    if isinstance(prior_result.data, CanonicalDocument):
        doc = prior_result.data
        text_hash = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()
        prov_hash = "|".join(f"{p.capability_id}:{p.stage}" for p in prior_result.provenance)
        material = f"{doc.document_id}:{doc.detected_type}:{len(doc.pages)}:{len(doc.tables)}:{text_hash}:{prov_hash}"
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
    options_str = json.dumps(dict(options), sort_keys=True) if options else ""
    metadata_str = json.dumps(dict(request.metadata), sort_keys=True) if request.metadata else ""
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
