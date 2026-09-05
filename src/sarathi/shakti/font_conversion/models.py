"""Models and Data Structures for Roopa Font Conversion in Sarathi V2."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from sarathi.sankalpa import ProvenanceRecord


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    """A masked span of text that must not be converted."""

    placeholder: str
    original_text: str
    span_type: str


@dataclass(frozen=True, slots=True)
class FontEvidence:
    """Evidence collected for a font run or segment."""

    raw_font_name: str | None = None
    canonical_font_family: str | None = None
    font_source: str = "unknown"  # direct_run_property, character_style, paragraph_style, style_inheritance, doc_defaults, theme, symbol_font, canonical_span_metadata, request_hint, text_detection, unknown
    text_evidence: str = ""
    language_hint: str | None = None
    script_hint: str | None = None
    document_part: str = "document"
    location: str = ""
    confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class ConversionCandidate:
    """A candidate legacy font profile evaluated against text evidence."""

    profile_id: str
    score: float
    positive_signatures: tuple[str, ...] = ()
    negative_signatures: tuple[str, ...] = ()
    mapping_coverage: float = 0.0
    mapped_token_count: int = 0
    unmapped_token_count: int = 0
    unmapped_tokens: tuple[str, ...] = ()
    is_structurally_valid: bool = True
    structural_defects: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversionDecision:
    """Decision made on a logical run or document segment."""

    decision: str  # convert, preserve, ambiguous, invalid, unsupported
    profile: str | None = None
    reason: str = ""  # exact_source_font_alias, known_modern_unicode_font, conflicting_profile_evidence, strong_text_evidence, insufficient_evidence, structural_failure
    candidate_rank: int = 0
    candidate_margin: float = 0.0


@dataclass(frozen=True, slots=True)
class LogicalRun:
    """A logical sequence of compatible source runs for non-destructive conversion."""

    runs: tuple[Any, ...]  # references to underlying XML or TextSpan elements
    text: str
    evidence: FontEvidence
    decision: ConversionDecision | None = None
    converted_text: str | None = None
    offsets: tuple[tuple[int, int], ...] = ()


@dataclass(slots=True)
class ConversionMetrics:
    """Detailed Pramana telemetry metrics for font conversion."""

    runs_scanned: int = 0
    runs_converted: int = 0
    runs_preserved: int = 0
    runs_ambiguous: int = 0
    profiles_used: tuple[str, ...] = ()
    mapped_tokens: int = 0
    unmapped_tokens: int = 0
    mapping_coverage: float = 1.0
    symbols_converted: int = 0
    symbols_unmapped: int = 0
    structural_failures: int = 0
    residual_legacy_runs: int = 0
    candidate_retries: int = 0
    quality_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ConversionPlan:
    """The single conversion truth binding CanonicalDocument, TXT, and DOCX outputs."""

    document_id: str
    source_input_id: str | None = None
    logical_runs: tuple[LogicalRun, ...] = ()
    profile_decisions: tuple[ConversionDecision, ...] = ()
    overall_metrics: ConversionMetrics = field(default_factory=ConversionMetrics)
    accepted: bool = False
    rejection_reason: str | None = None


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
    schema_version: str = "1.0.0"
    symbols: Mapping[str, str] = field(default_factory=dict)
    reverse_preferred: Mapping[str, str] = field(default_factory=dict)
    family_corrections: tuple[tuple[str, str], ...] = ()
    detection_signatures: tuple[str, ...] = ()
    negative_signatures: tuple[str, ...] = ()
    # Precompiled transducers
    compiled_forward_regex: re.Pattern | None = None
    compiled_reverse_regex: re.Pattern | None = None
    compiled_reverse_map: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FontConversionResult:
    """Result of converting legacy-encoded text to canonical Unicode."""

    converted_text: str
    original_text: str
    detected_profile: str | None
    confidence: float
    protected_spans_count: int
    provenance: tuple[ProvenanceRecord, ...] = ()
