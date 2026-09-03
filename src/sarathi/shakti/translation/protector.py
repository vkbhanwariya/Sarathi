"""Span Protection and Byte-for-Byte Restoration Engine for Translation.

Guarantees URLs, emails, dates, monetary amounts, numbers, percentages,
alphanumeric IDs/codes, references, and domain terminology survive translation 100% untouched.
"""

from __future__ import annotations

import re
from typing import Sequence

from sarathi.shakti.font_conversion.protector import (
    _DATE_RE,
    _EMAIL_RE,
    _ID_RE,
    _NUM_RE,
    _PERCENT_RE,
    _URL_RE,
    BaseSpanProtector,
)
from sarathi.shakti.translation.models import TranslationSpan


class TranslationProtector(BaseSpanProtector):
    """Protects and restores non-translatable factual spans."""

    def protect(self, text: str, custom_terms: Sequence[str] = ()) -> tuple[str, list[TranslationSpan]]:
        """Identify protected spans, replace them with unique PUA placeholders, and return them."""
        protected_spans: list[TranslationSpan] = []
        placeholder_idx = 0

        def _repl(match: re.Match, span_type: str) -> str:
            nonlocal placeholder_idx
            original = match.group(0)
            placeholder = self.format_placeholder(placeholder_idx)
            protected_spans.append(
                TranslationSpan(placeholder=placeholder, original_text=original, span_type=span_type)
            )
            placeholder_idx += 1
            return placeholder

        # 1. Protect Custom Terms (sorted by length descending to match longest matches first)
        if custom_terms:
            sorted_terms = sorted([t for t in custom_terms if t.strip()], key=len, reverse=True)
            if sorted_terms:
                term_pattern = re.compile("|".join(re.escape(t) for t in sorted_terms))
                text = term_pattern.sub(lambda m: _repl(m, "custom_term"), text)

        # 2. Protect URLs & Emails
        text = _URL_RE.sub(lambda m: _repl(m, "url"), text)
        text = _EMAIL_RE.sub(lambda m: _repl(m, "email"), text)

        # 3. Protect Percentages, Dates, Numbers, and IDs
        text = _PERCENT_RE.sub(lambda m: _repl(m, "percent"), text)
        text = _DATE_RE.sub(lambda m: _repl(m, "date"), text)
        text = _NUM_RE.sub(lambda m: _repl(m, "number"), text)
        text = _ID_RE.sub(lambda m: _repl(m, "id"), text)

        return text, protected_spans


__all__ = ["TranslationProtector"]
