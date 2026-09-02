"""Models and Data Structures for Roopa Font Conversion in Sarathi V2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from sarathi.sankalpa import ProvenanceRecord


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    """A masked span of text that must not be converted."""

    placeholder: str
    original_text: str
    span_type: str


@dataclass(frozen=True, slots=True)
class LegacyFontProfile:
    """Configuration and mappings for a legacy font encoding profile."""

    profile_id: str
    family: str
    name: str
    aliases: tuple[str, ...]
    prefixes: Mapping[str, str]
    postfix_reph: str
    reph_unicode: str
    mappings: Mapping[str, str]
    post_corrections: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class FontConversionResult:
    """Result of converting legacy-encoded text to canonical Unicode."""

    converted_text: str
    original_text: str
    detected_profile: str | None
    confidence: float
    protected_spans_count: int
    provenance: tuple[ProvenanceRecord, ...] = ()
