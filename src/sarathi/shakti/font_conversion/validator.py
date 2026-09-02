"""Integrity Validator for Roopa Font Conversion."""

from __future__ import annotations

from typing import Sequence

from sarathi.shakti.font_conversion.models import ProtectedSpan


class FontConversionValidator:
    """Validates that protected spans are preserved byte-for-byte in the final output."""

    def validate_protection_integrity(self, restored_text: str, original_spans: Sequence[ProtectedSpan]) -> bool:
        """Ensure every protected span exists verbatim in the output text."""
        for span in original_spans:
            if span.original_text not in restored_text:
                return False
        return True
