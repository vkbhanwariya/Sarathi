"""Translation Integrity Validator."""

from __future__ import annotations

from typing import Sequence

from sarathi.shakti.translation.models import TranslationSpan


class TranslationValidator:
    """Validates factual span preservation and output integrity."""

    def validate_spans(self, translated_text: str, spans: Sequence[TranslationSpan]) -> bool:
        """Verify that all original protected text spans exist in translated text byte-for-byte."""
        for span in spans:
            if span.original_text not in translated_text:
                return False
        return True
