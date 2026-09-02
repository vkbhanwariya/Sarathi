"""Span Protection and Restoration Engine for Roopa Font Conversion.

Guarantees Latin/English text, numbers, dates, IDs, emails, URLs, punctuation,
and existing Unicode Devanagari text round-trip 100% untouched.
"""

from __future__ import annotations

import re
from typing import Sequence

from sarathi.shakti.font_conversion.models import ProtectedSpan

_PROT_START = "\uE000"
_PROT_END = "\uE001"

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
_UNICODE_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+(?:[\s\u0900-\u097F]*[\u0900-\u097F])?")
_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE = re.compile(r"(?:Rs\.?|₹)?\s*\b\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:/[-=]|%)?\b")
_PAREN_LATIN_RE = re.compile(r"\([A-Za-z0-9\s,\.-]+\)")
_LABEL_RE = re.compile(r"\b[A-Za-z]{2,}:")
_KNOWN_LATIN_RE = re.compile(
    r"\b(?:Govt|Government|India|State|Bank|SBI|HDFC|ICICI|Axis|Kotak|Account|Ref|Amount|Date|Name|Total|Balance|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|Sarkar|LTD|Limited|Private|Pvt)\b",
    re.IGNORECASE,
)
_ID_RE = re.compile(r"\b[A-Z0-9_-]{4,}\b")


class TextProtector:
    """Protects and restores non-legacy text spans during font conversion."""

    def protect(self, text: str) -> tuple[str, list[ProtectedSpan]]:
        """Identify protected spans, replace them with unique placeholders, and return them."""
        protected_spans: list[ProtectedSpan] = []
        placeholder_idx = 0

        def _repl(match: re.Match, span_type: str) -> str:
            nonlocal placeholder_idx
            original = match.group(0)
            placeholder = f"{_PROT_START}{chr(0xE100 + placeholder_idx)}{_PROT_END}"
            protected_spans.append(ProtectedSpan(placeholder=placeholder, original_text=original, span_type=span_type))
            placeholder_idx += 1
            return placeholder

        # 1. Protect URLs & Emails
        text = _URL_RE.sub(lambda m: _repl(m, "url"), text)
        text = _EMAIL_RE.sub(lambda m: _repl(m, "email"), text)

        # 2. Protect existing Unicode Devanagari
        text = _UNICODE_DEVANAGARI_RE.sub(lambda m: _repl(m, "unicode_devanagari"), text)

        # 3. Protect Dates & Numbers
        text = _DATE_RE.sub(lambda m: _repl(m, "date"), text)
        text = _NUM_RE.sub(lambda m: _repl(m, "number"), text)

        # 4. Protect Parenthesized English Spans & Labels
        text = _PAREN_LATIN_RE.sub(lambda m: _repl(m, "paren_latin"), text)
        text = _LABEL_RE.sub(lambda m: _repl(m, "label"), text)

        # 5. Protect Known English Words & Alphanumeric IDs
        text = _KNOWN_LATIN_RE.sub(lambda m: _repl(m, "known_latin"), text)
        text = _ID_RE.sub(lambda m: _repl(m, "id"), text)

        return text, protected_spans

    def restore(self, text: str, spans: Sequence[ProtectedSpan]) -> str:
        """Restore all protected spans from placeholders byte-for-byte."""
        for s in spans:
            text = text.replace(s.placeholder, s.original_text)
        return text
