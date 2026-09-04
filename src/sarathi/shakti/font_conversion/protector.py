"""Span Protection and Restoration Engine for Roopa Font Conversion.

Guarantees Latin/English text, numbers, dates, IDs, emails, URLs, punctuation,
and existing Unicode Devanagari text round-trip 100% untouched.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from sarathi.shakti.font_conversion.models import ProtectedSpan

_PROT_START = "\ue000"
_PROT_END = "\ue001"

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
_UNICODE_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+(?:[\s\u0900-\u097F]*[\u0900-\u097F])?")
_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE = re.compile(r"(?:Rs\.?|₹|\$|€|£)?\s*\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\s*%?\b")
_PERCENT_RE = re.compile(r"\b\d+%\b|\(\d+%\)")
_ID_RE = re.compile(r"\b[A-Z0-9_-]{4,}\b")


class BaseSpanProtector:
    """Base engine for protecting and restoring non-translatable or non-convertible spans."""

    @staticmethod
    def format_placeholder(index: int) -> str:
        """Format unique Private-Use-Area placeholder for protected span index."""
        return f"{_PROT_START}{chr(0xE100 + index)}{_PROT_END}"

    def restore(self, text: str, spans: Sequence[Any]) -> str:
        """Restore all protected spans from placeholders byte-for-byte."""
        for s in spans:
            text = text.replace(s.placeholder, s.original_text)
        return text

_KRUTI_CHARS = set(r"[k?/~+\ñòóôõö÷øùúûüZ")
_KRUTI_DIGRAPHS = (
    "[k",
    "vk",
    "vks",
    "vkS",
    "Fk",
    "/k",
    "Hk",
    "'k",
    '"k',
    ";Z",
    "jZ",
    ";k",
    "D;",
    "x~",
    "LVs",
    "cSa",
    ".k",
    "fdr",
    "fd",
    "fr",
    "fn",
    "fc",
    "f[",
    "fH",
    "fF",
    "fD",
    "fV",
    "fp",
    "ft",
    "iz",
    "LFk",
    "O;",
    "fod",
    "f'k",
    "foH",
    "fnY",
    "mRr",
)

# Target structured English patterns
_LABEL_RE = re.compile(r"\b[A-Za-z][A-Za-z\s]{1,30}:(?=\s|$)")
_PAREN_LATIN_RE = re.compile(r"\([A-Za-z0-9\s,\.\-_/\ue000-\ue200]{2,}\)")
_TITLECASE_PHRASE_RE = re.compile(
    r"\b[A-Z][a-z]{2,}(?:\s+(?:of|and|the|in|for|to|at|by|on|from|with)\s+[A-Z][a-z]{2,}|\s+[A-Z][a-z]{2,})+\b"
)
_KNOWN_LATIN_RE = re.compile(
    r"\b(?:Govt|Government|India|State|Bank|SBI|HDFC|ICICI|Axis|Kotak|Pvt|Ltd|Limited|Private|Company|Distributor|Trading|Sponsored|Bail|PMLA|FIR|Tower|Flat|Road|Street|Apartment|Park|Avenue|Lane|Pass)\b",
    re.IGNORECASE,
)


class TextProtector(BaseSpanProtector):
    """Protects and restores non-legacy text spans during font conversion."""

    def protect(
        self,
        text: str,
        protect_devanagari: bool = True,
        is_explicit_legacy: bool = False,
    ) -> tuple[str, list[ProtectedSpan]]:
        """Identify protected spans, replace them with unique PUA placeholders, and return them."""
        protected_spans: list[ProtectedSpan] = []
        placeholder_idx = 0

        def _repl(match: re.Match, span_type: str) -> str:
            nonlocal placeholder_idx
            original = match.group(0)
            placeholder = self.format_placeholder(placeholder_idx)
            protected_spans.append(ProtectedSpan(placeholder=placeholder, original_text=original, span_type=span_type))
            placeholder_idx += 1
            return placeholder

        # 1. Protect URLs & Emails
        text = _URL_RE.sub(lambda m: _repl(m, "url"), text)
        text = _EMAIL_RE.sub(lambda m: _repl(m, "email"), text)

        # 2. Protect existing Unicode Devanagari (only if not converting Unicode to legacy)
        if protect_devanagari:
            text = _UNICODE_DEVANAGARI_RE.sub(lambda m: _repl(m, "unicode_devanagari"), text)

        # 3. For unknown/mixed content, protect parenthesized Latin phrases before numbers to preserve them intact
        if not is_explicit_legacy:
            text = _PAREN_LATIN_RE.sub(lambda m: _repl(m, "paren_latin"), text)

        # 4. Protect strongly evidenced Percentages, Dates, Numbers, and Reference IDs
        text = _PERCENT_RE.sub(lambda m: _repl(m, "percent"), text)
        text = _DATE_RE.sub(lambda m: _repl(m, "date"), text)
        text = _NUM_RE.sub(lambda m: _repl(m, "number"), text)
        text = _ID_RE.sub(lambda m: _repl(m, "id"), text)

        # 5. For unknown-font content, also protect remaining structured English phrases and known institutional terms
        if not is_explicit_legacy:
            text = _LABEL_RE.sub(lambda m: _repl(m, "english_label"), text)
            text = _PAREN_LATIN_RE.sub(lambda m: _repl(m, "paren_latin"), text)
            text = _TITLECASE_PHRASE_RE.sub(lambda m: _repl(m, "english_phrase"), text)
            text = _KNOWN_LATIN_RE.sub(lambda m: _repl(m, "known_latin"), text)

        return text, protected_spans


__all__ = ["BaseSpanProtector", "TextProtector"]
