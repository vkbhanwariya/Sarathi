"""Post-Translation Factual-Equivalence and Quality Validator.

Verifies that critical factual tokens (dates, monetary amounts, statutory IDs,
percentages, URLs, emails) in the source text survived translation into the target text,
and detects untranslated residue.
"""

from __future__ import annotations

import re
from collections import Counter

from sarathi.sankalpa import WarningRecord
from sarathi.shakti.text.typography import normalize_devanagari_numerals
from sarathi.shakti.translation.models import TranslationDirection

# Statutory IDs: PAN, GSTIN, IFSC, TAN, CIN, CNR
_STATUTORY_ID_RE = re.compile(
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"  # PAN
    r"|\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"  # GSTIN
    r"|\b[A-Z]{4}0[A-Z0-9]{6}\b"  # IFSC
    r"|\b[A-Z]{4}[0-9]{5}[A-Z]\b"  # TAN
    r"|\b[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b"  # CIN
    r"|\b[A-Z]{4}[0-9]{8}[0-9]{4}\b",  # CNR
    re.IGNORECASE,
)
_ALPHANUMERIC_ID_RE = re.compile(
    r"\b(?=[A-Za-z0-9_-]{4,}\b)(?:[A-Za-z]+[0-9]|[0-9]+[A-Za-z])[A-Za-z0-9_-]*\b"
)

_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE = re.compile(r"\b\d+(?:,\d+)*(?:\.\d+)?\b")
_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _normalize_token(tok: str) -> str:
    """Normalize digits and delimiters for multiset comparison."""
    norm = normalize_devanagari_numerals(tok)
    if re.fullmatch(r"\d+(?:,\d+)*(?:\.\d+)?", norm):
        norm = norm.replace(",", "")
    return norm.strip().lower()


def extract_factual_tokens(text: str) -> list[str]:
    """Extract factual tokens (emails, URLs, statutory IDs, dates, numbers) from text."""
    if not text:
        return []

    norm_text = normalize_devanagari_numerals(text)
    tokens: list[str] = []

    # 1. URLs and Emails
    for m in _URL_RE.finditer(norm_text):
        tokens.append(_normalize_token(m.group(0)))
    for m in _EMAIL_RE.finditer(norm_text):
        tokens.append(_normalize_token(m.group(0)))

    # 2. Statutory and Alphanumeric IDs
    for m in _STATUTORY_ID_RE.finditer(norm_text):
        tokens.append(_normalize_token(m.group(0)))
    for m in _ALPHANUMERIC_ID_RE.finditer(norm_text):
        tokens.append(_normalize_token(m.group(0)))

    # 3. Dates
    for m in _DATE_RE.finditer(norm_text):
        tokens.append(_normalize_token(m.group(0)))

    # 4. Standalone numbers / amounts (filter out 1-2 digit trivial numbers)
    for m in _NUM_RE.finditer(norm_text):
        clean_num = m.group(0).replace(",", "")
        if len(clean_num) >= 3 or "." in clean_num:
            tokens.append(_normalize_token(m.group(0)))

    return tokens


def validate_factual_equivalence(
    source_text: str,
    target_text: str,
    direction: TranslationDirection = TranslationDirection.HI_TO_EN,
) -> list[WarningRecord]:
    """Validate that factual tokens from source text exist in translated text.

    Compares normalized multisets of factual entities and returns WarningRecords
    for any missing facts or abnormal untranslated content.
    """
    warnings: list[WarningRecord] = []
    if not source_text or not target_text:
        return warnings

    src_tokens = Counter(extract_factual_tokens(source_text))
    tgt_tokens = Counter(extract_factual_tokens(target_text))

    for token, src_count in src_tokens.items():
        tgt_count = tgt_tokens.get(token, 0)
        if tgt_count < src_count:
            warnings.append(
                WarningRecord(
                    code="TRANSLATION_FACTUAL_DISCREPANCY",
                    message=f"Factual token '{token}' in source document was missing or mismatched in translated text.",
                    stage="translation",
                    context={"token": token, "source_count": src_count, "target_count": tgt_count},
                )
            )

    # Sanity check for untranslated residue
    if direction == TranslationDirection.HI_TO_EN:
        dev_chars = sum(1 for c in target_text if "\u0900" <= c <= "\u097f")
        total_letters = sum(1 for c in target_text if c.isalpha())
        if total_letters > 30 and (dev_chars / total_letters) > 0.35:
            warnings.append(
                WarningRecord(
                    code="UNTRANSLATED_SEGMENT_DETECTED",
                    message="High proportion of untranslated Devanagari script remaining in English translation.",
                    stage="translation",
                    context={"devanagari_ratio": round(dev_chars / total_letters, 3)},
                )
            )
    elif direction == TranslationDirection.EN_TO_HI:
        words = target_text.split()
        if len(words) > 15:
            latin_words = sum(1 for w in words if re.fullmatch(r"[A-Za-z]+", w))
            if (latin_words / len(words)) > 0.65:
                warnings.append(
                    WarningRecord(
                        code="UNTRANSLATED_SEGMENT_DETECTED",
                        message="High proportion of untranslated English words remaining in Hindi translation.",
                        stage="translation",
                        context={"latin_word_ratio": round(latin_words / len(words), 3)},
                    )
                )

    return warnings
