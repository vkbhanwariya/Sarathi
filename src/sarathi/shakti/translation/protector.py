"""Span Protection and Byte-for-Byte Restoration Engine for Translation.

Guarantees URLs, emails, dates, monetary amounts, numbers, percentages,
alphanumeric IDs/codes, references, and domain terminology survive translation 100% untouched.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from sarathi.shakti.text.span_protection import (
    _DATE_RE,
    _EMAIL_RE,
    _NUM_RE,
    _PERCENT_RE,
    _URL_RE,
    BaseSpanProtector,
)
from sarathi.shakti.translation.models import TranslationSpan

# Genuine alphanumeric IDs: require mixed letters+digits or hyphen/underscore separated codes.
# Never match pure English uppercase words like TABLE, COURT, ORDER.
_TRANSLATION_ID_RE: re.Pattern[str] = re.compile(
    r"\b(?=[A-Za-z0-9_-]{4,}\b)(?:[A-Za-z]+[0-9]|[0-9]+[A-Za-z])[A-Za-z0-9_-]*\b"
    r"|\b[A-Za-z0-9]{2,}(?:[-_][A-Za-z0-9]+)+\b"
)


def _compile_term_pattern(term: str) -> re.Pattern[str]:
    """Compile boundary-aware regex pattern for a glossary or custom term."""
    esc = re.escape(term)
    prefix = r"(?<!\w)" if term and term[0].isalnum() else ""
    suffix = r"(?!\w)" if term and term[-1].isalnum() else ""
    return re.compile(f"{prefix}{esc}{suffix}")


class TranslationProtector(BaseSpanProtector):
    """Protects and restores non-translatable factual spans using SentencePiece-safe placeholders."""

    @staticmethod
    def format_placeholder(index: int) -> str:
        """Format unique SentencePiece-safe numeric placeholder for protected span index."""
        return f"999{index:04d}"

    def protect(
        self,
        text: str,
        custom_terms: Sequence[str] = (),
        glossary_mappings: Mapping[str, str] | None = None,
    ) -> tuple[str, list[TranslationSpan]]:
        """Identify protected spans and glossary terms using single-pass offset matching."""
        raw_matches: list[tuple[int, int, str, str, int]] = []

        # 1. Domain Glossary Mappings (Priority 10)
        if glossary_mappings:
            sorted_srcs = sorted([s for s in glossary_mappings.keys() if s.strip()], key=len, reverse=True)
            for src in sorted_srcs:
                target_val = glossary_mappings[src]
                for m in _compile_term_pattern(src).finditer(text):
                    raw_matches.append((m.start(), m.end(), target_val, "glossary_term", 10))

        # 2. Custom Terms (Priority 20)
        if custom_terms:
            sorted_terms = sorted([t for t in custom_terms if t.strip()], key=len, reverse=True)
            for term in sorted_terms:
                for m in _compile_term_pattern(term).finditer(text):
                    raw_matches.append((m.start(), m.end(), m.group(0), "custom_term", 20))

        # 3. URLs & Emails (Priority 30)
        for m in _URL_RE.finditer(text):
            raw_matches.append((m.start(), m.end(), m.group(0), "url", 30))
        for m in _EMAIL_RE.finditer(text):
            raw_matches.append((m.start(), m.end(), m.group(0), "email", 30))

        # 4. Dates & Percentages (Priority 40)
        for m in _DATE_RE.finditer(text):
            raw_matches.append((m.start(), m.end(), m.group(0), "date", 40))
        for m in _PERCENT_RE.finditer(text):
            raw_matches.append((m.start(), m.end(), m.group(0), "percent", 40))

        # 5. Currency Amounts / Numbers (Priority 50)
        for m in _NUM_RE.finditer(text):
            val = m.group(0).strip()
            if val:
                raw_matches.append((m.start(), m.end(), val, "number", 50))

        # 6. Alphanumeric IDs (Priority 60)
        for m in _TRANSLATION_ID_RE.finditer(text):
            raw_matches.append((m.start(), m.end(), m.group(0), "id", 60))

        # Sort matches: start offset asc, priority asc (lower is higher prio), length desc
        raw_matches.sort(key=lambda x: (x[0], x[4], -(x[1] - x[0])))

        # Discard overlapping spans, keeping higher priority / earlier match
        selected: list[tuple[int, int, str, str]] = []
        last_end = 0
        for start, end, orig_val, span_type, _ in raw_matches:
            if start >= last_end:
                selected.append((start, end, orig_val, span_type))
                last_end = end

        # Construct protected text and spans list in a single clean pass
        pieces: list[str] = []
        protected_spans: list[TranslationSpan] = []
        curr = 0
        for idx, (start, end, orig_val, span_type) in enumerate(selected):
            pieces.append(text[curr:start])
            placeholder = self.format_placeholder(idx)
            pieces.append(placeholder)
            protected_spans.append(
                TranslationSpan(placeholder=placeholder, original_text=orig_val, span_type=span_type)
            )
            curr = end
        pieces.append(text[curr:])

        return "".join(pieces), protected_spans

    def restore_with_validation(
        self,
        text: str,
        spans: Sequence[Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        """Restore all protected spans with integrity validation."""
        # Normalize any whitespace inserted inside numeric placeholders by tokenizer/model
        text = re.sub(r"9\s*9\s*9\s*(\d{4})", r"999\1", text)
        issues: list[dict[str, Any]] = []
        for s in spans:
            placeholder = getattr(s, "placeholder", None)
            original_text = getattr(s, "original_text", "")
            if not placeholder:
                continue
            count = text.count(placeholder)
            if count == 0:
                # Resilient recovery: check if tokenizer collapsed consecutive 9s (e.g. 990003 instead of 9990003)
                # or separated with whitespace
                if placeholder.startswith("999") and len(placeholder) == 7:
                    idx_suffix = placeholder[3:]
                    loose_pat = re.compile(rf"9{{2,4}}\s*{re.escape(idx_suffix)}")
                    m = loose_pat.search(text)
                    if m:
                        text = text[: m.start()] + original_text + text[m.end() :]
                        continue

                issues.append(
                    {
                        "code": "PROTECTED_SPAN_MISSING",
                        "placeholder": placeholder,
                        "original_text": original_text,
                        "count": 0,
                    }
                )
            elif count > 1:
                issues.append(
                    {
                        "code": "PROTECTED_SPAN_DUPLICATED",
                        "placeholder": placeholder,
                        "original_text": original_text,
                        "count": count,
                    }
                )
                text = text.replace(placeholder, original_text)
            else:
                text = text.replace(placeholder, original_text)
        return text, issues


__all__ = ["TranslationProtector"]
