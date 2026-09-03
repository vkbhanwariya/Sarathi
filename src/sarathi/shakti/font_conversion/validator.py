"""Integrity and Devanagari Structural Validator for Roopa Font Conversion."""

from __future__ import annotations

import re
from typing import Sequence

from sarathi.shakti.font_conversion.models import ProtectedSpan

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


class FontConversionValidator:
    """Validates protected span preservation and structural Devanagari integrity."""

    def validate_protection_integrity(self, restored_text: str, original_spans: Sequence[ProtectedSpan]) -> bool:
        """Ensure every protected span exists verbatim in the output text."""
        for span in original_spans:
            if span.original_text not in restored_text:
                return False
        return True

    def validate_devanagari_structure(self, text: str) -> tuple[bool, list[str]]:
        """Validate structural soundness of converted Devanagari Unicode text.

        Detects:
        - Orphan / unattached dependent matras or virama at word boundaries
        - Doubled virama (््)
        - Successive contradictory vowel matras
        - Residual untranslated legacy glyph markers

        Returns:
            (is_valid, list_of_defects)
        """
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

        return (len(defects) == 0, defects)
