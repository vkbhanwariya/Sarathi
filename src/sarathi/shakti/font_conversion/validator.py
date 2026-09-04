"""Integrity and Devanagari Structural Validator for Roopa Font Conversion."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from sarathi.shakti.font_conversion.models import LegacyFontProfile, ProtectedSpan

# Dependent vowel matras that cannot start a word or appear without a preceding consonant
_DEPENDENT_MATRAS = "\u093a-\u094c\u094e\u094f\u0955-\u0957\u0962\u0963"
_DEVANAGARI_CONSONANTS = "\u0915-\u0939\u0958-\u095f\u0978-\u097f"
_DEVANAGARI_INDEPENDENT_VOWELS = "\u0904-\u0914\u0960\u0961\u0972-\u0977"

# Patterns detecting malformed Devanagari structure:
# 1. Orphan matra at the start of string or following whitespace/punctuation
_ORPHAN_MATRA_RE = re.compile(rf"(?:^|[\s\(\[\{{\"'\-–—:;,\.!?])[{_DEPENDENT_MATRAS}\u094d]")
# 2. Doubled virama
_DOUBLED_VIRAMA_RE = re.compile(r"\u094d{2,}")
# 3. Two successive full vowel matras (e.g. ाो, ुे)
_CONSECUTIVE_FULL_MATRAS_RE = re.compile(rf"[{_DEPENDENT_MATRAS}]{{2,}}")
# 4. Residual Kruti legacy special markers that should never appear in converted Hindi
_RESIDUAL_KRUTI_GLYPHS = set("ñòóôõö÷øùúûü")
# 5. Distinctive Remington digraphs that should not survive conversion in Devanagari runs
_RESIDUAL_DIGRAPHS = ("[k", "vk", "vks", "vkS", "Fk", "/k", "Hk", ";Z", "jZ")


@dataclass(frozen=True, slots=True)
class MappingMetrics:
    """Factual mapping coverage and residual token metrics."""

    total_tokens: int
    mapped_tokens: int
    protected_tokens: int
    unmapped_tokens: int
    mapping_coverage: float
    unmapped_samples: tuple[str, ...] = ()


class FontConversionValidator:
    """Validates protected span preservation, mapping coverage, and structural Devanagari integrity."""

    def validate_protection_integrity(self, restored_text: str, original_spans: Sequence[ProtectedSpan]) -> bool:
        """Ensure every protected span exists verbatim in the output text."""
        for span in original_spans:
            if span.original_text not in restored_text:
                return False
        return True

    def calculate_mapping_coverage(
        self,
        source_text: str,
        profile: LegacyFontProfile,
        protected_spans: Sequence[ProtectedSpan] = (),
    ) -> MappingMetrics:
        """Calculate token mapping coverage and identify unmapped legacy tokens."""
        if not source_text or not source_text.strip():
            return MappingMetrics(0, 0, 0, 0, 1.0, ())

        protected_tokens = len(protected_spans)
        tokens = source_text.split()
        total_tokens = len(tokens)

        mapped_count = 0
        unmapped_count = 0
        unmapped_samples: list[str] = []

        regex = profile.compiled_forward_regex
        for t in tokens:
            # Skip placeholders if present in token
            if "\ue000" in t:
                continue
            if regex is not None:
                matches = regex.findall(t)
                matched_chars = sum(len(m) for m in matches)
                if matched_chars >= max(1, len(t) * 0.5):
                    mapped_count += 1
                else:
                    unmapped_count += 1
                    if len(unmapped_samples) < 5:
                        unmapped_samples.append(t)
            else:
                unmapped_count += 1

        active_total = mapped_count + unmapped_count
        coverage = (mapped_count / active_total) if active_total > 0 else 1.0

        return MappingMetrics(
            total_tokens=total_tokens,
            mapped_tokens=mapped_count,
            protected_tokens=protected_tokens,
            unmapped_tokens=unmapped_count,
            mapping_coverage=coverage,
            unmapped_samples=tuple(unmapped_samples),
        )

    def validate_devanagari_structure(self, text: str) -> tuple[bool, list[str]]:
        """Validate structural soundness of converted Devanagari Unicode text."""
        defects: list[str] = []

        if _ORPHAN_MATRA_RE.search(text):
            defects.append("ORPHAN_MATRA_OR_VIRAMA_AT_BOUNDARY")

        if _DOUBLED_VIRAMA_RE.search(text):
            defects.append("DOUBLED_VIRAMA")

        if _CONSECUTIVE_FULL_MATRAS_RE.search(text):
            defects.append("CONSECUTIVE_DEPENDENT_MATRAS")

        found_residuals = [ch for ch in text if ch in _RESIDUAL_KRUTI_GLYPHS]
        if found_residuals:
            defects.append(f"RESIDUAL_LEGACY_GLYPHS:{len(found_residuals)}")

        # Check for unmapped Remington digraphs in converted text
        for d in _RESIDUAL_DIGRAPHS:
            if d in text:
                defects.append(f"RESIDUAL_UNMAPPED_DIGRAPH:{d}")
                break

        return (len(defects) == 0, defects)


def validate_devanagari_structure(text: str) -> tuple[bool, list[str]]:
    """Validate structural soundness of converted Devanagari Unicode text."""
    return FontConversionValidator().validate_devanagari_structure(text)


def calculate_mapping_coverage(
    source_text: str,
    profile: LegacyFontProfile,
    protected_spans: Sequence[ProtectedSpan] = (),
) -> MappingMetrics:
    """Calculate token mapping coverage and identify unmapped legacy tokens."""
    return FontConversionValidator().calculate_mapping_coverage(source_text, profile, protected_spans)


__all__ = [
    "FontConversionValidator",
    "MappingMetrics",
    "calculate_mapping_coverage",
    "validate_devanagari_structure",
]
