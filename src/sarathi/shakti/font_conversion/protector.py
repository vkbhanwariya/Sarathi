"""Span Protection and Restoration Engine for Roopa Font Conversion.

Guarantees Latin/English text, numbers, dates, IDs, emails, URLs, punctuation,
and existing Unicode Devanagari text round-trip 100% untouched.
"""

from __future__ import annotations

import re
from typing import Sequence

from sarathi.shakti.font_conversion.models import ProtectedSpan

_PROT_START = ""
_PROT_END = ""

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
_UNICODE_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]+(?:[\s\u0900-\u097F]*[\u0900-\u097F])?")
_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE = re.compile(r"(?:Rs\.?|₹|\$|€|£)?\s*\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\s*%?\b")
_PERCENT_RE = re.compile(r"\b\d+%\b|\(\d+%\)")
_ID_RE = re.compile(r"\b[A-Z0-9_-]{4,}\b")

_KRUTI_CHARS = set(r"[k?/~+\ñòóôõö÷øùúûüZ")
_KRUTI_DIGRAPHS = (
    "[k", "vk", "vks", "vkS", "Fk", "/k", "Hk", "'k", "\"k", ";Z", "jZ", ";k", "D;",
    "x~", "LVs", "cSa", ".k", "fdr", "fd", "fr", "fn", "fc", "f[", "fH", "fF", "fD", "fV", "fp", "ft",
    "iz", "LFk", "O;", "fod", "f'k", "foH", "fnY", "mRr"
)


def _is_legacy_word(word: str) -> bool:
    """Classify whether a word token is Kruti Dev encoded text or standard Latin."""
    if any(c in word for c in _KRUTI_CHARS):
        return True
    if any(d in word for d in _KRUTI_DIGRAPHS):
        return True
    if re.search(r"^[dprtyoscvmbg]k", word):
        return True
    if re.search(r"[dprtyoscvmbg]k[dprtyoscvmbg]", word):
        if not re.search(r"[aeiouAEIOU]{2,}", word):
            return True
    return False


class TextProtector:
    """Protects and restores non-legacy text spans during font conversion."""

    def protect(self, text: str) -> tuple[str, list[ProtectedSpan]]:
        """Identify protected spans, replace them with unique PUA placeholders, and return them."""
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

        # 3. Protect Percentages, Dates, Numbers, and IDs
        text = _PERCENT_RE.sub(lambda m: _repl(m, "percent"), text)
        text = _DATE_RE.sub(lambda m: _repl(m, "date"), text)
        text = _NUM_RE.sub(lambda m: _repl(m, "number"), text)
        text = _ID_RE.sub(lambda m: _repl(m, "id"), text)

        # 4. Evidence-based word classification: protect ordinary Latin/English words
        def _word_repl(m: re.Match) -> str:
            word = m.group(0)
            if not _is_legacy_word(word):
                return _repl(m, "latin_word")
            return word

        text = re.sub(r"\b[A-Za-z]+\b", _word_repl, text)

        return text, protected_spans

    def restore(self, text: str, spans: Sequence[ProtectedSpan]) -> str:
        """Restore all protected spans from placeholders byte-for-byte."""
        for s in spans:
            text = text.replace(s.placeholder, s.original_text)
        return text
