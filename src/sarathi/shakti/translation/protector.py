"""Span Protection and Byte-for-Byte Restoration Engine for Translation.

Guarantees URLs, emails, dates, monetary amounts, numbers, percentages,
alphanumeric IDs/codes, references, and domain terminology survive translation 100% untouched.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

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
_FMT_TAG_RE: re.Pattern[str] = re.compile(r"</?fmt\b[^>]*>")


@dataclass(frozen=True, slots=True)
class _CompiledTermGroup:
    pattern: re.Pattern[str]
    lookup: dict[str, str]
    lower_lookup: dict[str, str]
    is_ignore_case: bool


# Devanagari character class including vowel signs, matras, viramas, anusvaras
_DEV_WORD_CHARS = r"\w\u0900-\u0963\u0966-\u096f\u0971-\u097f"


@lru_cache(maxsize=1024)
def _compile_term_pattern(term: str) -> re.Pattern[str]:
    """Compile boundary-aware regex pattern for a single term."""
    esc = re.escape(term)
    prefix = rf"(?<![{_DEV_WORD_CHARS}])" if term and term[0].isalnum() else ""
    suffix = rf"(?![{_DEV_WORD_CHARS}])" if term and term[-1].isalnum() else ""
    flags = re.IGNORECASE if any(ord(c) < 128 and c.isalpha() for c in term) else 0
    return re.compile(f"{prefix}{esc}{suffix}", flags)


@lru_cache(maxsize=32)
def _compile_glossary_groups(entries: tuple[tuple[str, str], ...]) -> tuple[_CompiledTermGroup, ...]:
    """Partition glossary mappings into at most 8 alternation groups and compile cached matchers."""
    buckets: dict[tuple[bool, bool, bool], list[tuple[str, str]]] = defaultdict(list)
    for src, tgt in entries:
        src_clean = src.strip()
        if not src_clean:
            continue
        p = bool(src_clean[0].isalnum() or ("\u0900" <= src_clean[0] <= "\u097f"))
        s = bool(src_clean[-1].isalnum() or ("\u0900" <= src_clean[-1] <= "\u097f"))
        i = any(ord(c) < 128 and c.isalpha() for c in src_clean)
        buckets[(p, s, i)].append((src_clean, tgt))

    compiled: list[_CompiledTermGroup] = []
    for (p, s, i), items in buckets.items():
        items.sort(key=lambda x: len(x[0]), reverse=True)
        prefix = rf"(?<![{_DEV_WORD_CHARS}])" if p else ""
        suffix = rf"(?![{_DEV_WORD_CHARS}])" if s else ""
        flags = re.IGNORECASE if i else 0
        pattern_str = f"{prefix}(?:{'|'.join(re.escape(k) for k, _ in items)}){suffix}"
        rgx = re.compile(pattern_str, flags)
        lookup = {k: v for k, v in items}
        lower_lookup = {k.lower(): v for k, v in items} if i else {}
        compiled.append(_CompiledTermGroup(rgx, lookup, lower_lookup, i))
    return tuple(compiled)


@lru_cache(maxsize=32)
def _compile_custom_term_groups(terms: tuple[str, ...]) -> tuple[_CompiledTermGroup, ...]:
    """Partition custom terms into at most 8 alternation groups and compile cached matchers."""
    buckets: dict[tuple[bool, bool, bool], list[str]] = defaultdict(list)
    for term in terms:
        t_clean = term.strip()
        if not t_clean:
            continue
        p = bool(t_clean[0].isalnum() or ("\u0900" <= t_clean[0] <= "\u097f"))
        s = bool(t_clean[-1].isalnum() or ("\u0900" <= t_clean[-1] <= "\u097f"))
        i = any(ord(c) < 128 and c.isalpha() for c in t_clean)
        buckets[(p, s, i)].append(t_clean)

    compiled: list[_CompiledTermGroup] = []
    for (p, s, i), items in buckets.items():
        items.sort(key=len, reverse=True)
        prefix = rf"(?<![{_DEV_WORD_CHARS}])" if p else ""
        suffix = rf"(?![{_DEV_WORD_CHARS}])" if s else ""
        flags = re.IGNORECASE if i else 0
        pattern_str = f"{prefix}(?:{'|'.join(re.escape(k) for k in items)}){suffix}"
        rgx = re.compile(pattern_str, flags)
        compiled.append(_CompiledTermGroup(rgx, {}, {}, i))
    return tuple(compiled)


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
        raw_matches: list[tuple[int, int, str, str, int]] = []

        # 0. Document Formatting Tags (Priority 5 - highest: must never reach NMT model)
        for m in _FMT_TAG_RE.finditer(text):
            raw_matches.append((m.start(), m.end(), m.group(0), "fmt_tag", 5))

        # 1. Domain Glossary Mappings (Priority 10)
        if glossary_mappings:
            cache_key = (
                glossary_mappings if isinstance(glossary_mappings, tuple) else tuple(sorted(glossary_mappings.items()))
            )
            for group in _compile_glossary_groups(cache_key):
                for m in group.pattern.finditer(text):
                    val = m.group(0)
                    tgt = group.lookup.get(val)
                    if tgt is None and group.is_ignore_case:
                        tgt = group.lower_lookup.get(val.lower())
                    if tgt is not None:
                        raw_matches.append((m.start(), m.end(), tgt, "glossary_term", 10))

        # 2. Custom Terms (Priority 20)
        if custom_terms:
            c_key = custom_terms if isinstance(custom_terms, tuple) else tuple(sorted(custom_terms))
            for group in _compile_custom_term_groups(c_key):
                for m in group.pattern.finditer(text):
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
            val = m.group(0)
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

            # Absorb any model-hallucinated trailing zero digits attached to the placeholder
            pat = re.compile(rf"{re.escape(placeholder)}0*")
            matches = list(pat.finditer(text))
            count = len(matches)

            if count == 0:
                # Resilient recovery: check if tokenizer collapsed consecutive 9s (e.g. 990003 instead of 9990003)
                # or separated with whitespace
                if placeholder.startswith("999") and len(placeholder) == 7:
                    idx_suffix = placeholder[3:]
                    loose_pat = re.compile(rf"9{{2,4}}\s*{re.escape(idx_suffix)}0*")
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
                text = pat.sub(lambda _: original_text, text)
            else:
                text = pat.sub(lambda _: original_text, text)
        return text, issues


__all__ = ["TranslationProtector"]
