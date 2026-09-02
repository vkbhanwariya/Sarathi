"""Contract 1: Stable Privacy-Safe Cache Key Computation for Smriti."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from sarathi.sankalpa import ExecutionProfile, InputRef, Request


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


def compute_cache_key(
    request: Request,
    capability_id: str,
    plugin_version: str = "1.0.0",
    custom_options: Mapping[str, object] | None = None,
) -> CacheKey:
    """Compute canonical deterministic cache key for a capability execution attempt."""
    fingerprint = compute_input_fingerprint(request.inputs)
    options = custom_options or request.custom_options
    options_str = json.dumps(dict(options), sort_keys=True) if options else ""

    content = (
        f"{capability_id}:{plugin_version}:{request.profile.value}:"
        f"{fingerprint}:{options_str}"
    )
    key_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return CacheKey(
        capability_id=capability_id,
        fingerprint=fingerprint,
        profile=request.profile.value,
        key_hash=key_hash,
    )
