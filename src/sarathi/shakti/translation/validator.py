"""Post-Translation Factual-Equivalence and Quality Validator.

Verifies that critical factual tokens (dates, monetary amounts, statutory IDs,
percentages, URLs, emails) in the source text survived translation into the target text,
and detects untranslated residue.
"""

from __future__ import annotations

import re
from collections import Counter

from sarathi.sankalpa import WarningRecord
from sarathi.shakti.statutory.checksums import STATUTORY_ID_BOUNDED_PATTERN
from sarathi.shakti.text.typography import normalize_devanagari_numerals
from sarathi.shakti.translation.models import TranslationDirection

# Statutory IDs: PAN, GSTIN, IFSC, TAN, CIN, CNR
_STATUTORY_ID_RE = STATUTORY_ID_BOUNDED_PATTERN
_ALPHANUMERIC_ID_RE = re.compile(
    r"\b(?=[A-Za-z0-9_-]{4,}\b)(?:[A-Za-z]+[0-9]|[0-9]+[A-Za-z])[A-Za-z0-9_-]*\b"
)

_DATE_RE = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_PERCENT_RE = re.compile(r"(?<!\w)[-+]?\d+(?:,\d+)*(?:\.\d+)?\s*%", re.IGNORECASE)
_CURRENCY_RE = re.compile(
    r"(?:₹|Rs\.?|INR|रु\.?|\$|USD|€|EUR|£|GBP)\s*[-+]?\d+(?:,\d+)*(?:\.\d+)?"
    r"|(?<!\w)[-+]?\d+(?:,\d+)*(?:\.\d+)?\s*(?:₹|Rs\.?|INR|रु\.?|रुपये|\$|USD|€|EUR|£|GBP)(?!\w)",
    re.IGNORECASE,
)
_NUM_RE = re.compile(r"(?<!\w)[-+]?\d+(?:,\d+)*(?:\.\d+)?(?!\w)")
_EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


def _parse_currency(raw: str) -> tuple[str, str]:
    """Parse raw currency expression into canonical currency prefix and numeric amount string."""
    raw_lower = raw.lower()
    if any(k in raw_lower for k in ("$", "usd")):
        sym = "$"
    elif any(k in raw_lower for k in ("€", "eur")):
        sym = "€"
    elif any(k in raw_lower for k in ("£", "gbp")):
        sym = "£"
    else:
        sym = "₹"
    m = re.search(r"[-+]?\d+(?:,\d+)*(?:\.\d+)?", raw)
    amt = m.group(0) if m else raw
    return sym, amt


def _normalize_token(tok: str) -> str:
    """Normalize digits, signs, percentages, and delimiters for multiset comparison."""
    norm = normalize_devanagari_numerals(tok).strip()
    is_pct = norm.endswith("%")
    core = norm[:-1].strip() if is_pct else norm
    m = re.fullmatch(r"([-+]?)(\d+(?:,\d+)*(?:\.\d+)?)", core)
    if m:
        sign, digits = m.group(1), m.group(2)
        digits = digits.replace(",", "")
        core = f"{sign}{digits}"
        norm = f"{core}%" if is_pct else core
    return norm.strip().lower()


def extract_factual_tokens(text: str) -> list[str]:
    """Extract factual tokens (emails, URLs, statutory IDs, dates, percentages, currencies, numbers) from text.

    Applies prioritized span masking so higher-precedence entities (URLs, emails,
    statutory IDs, dates, percentages, currencies) prevent their constituent substrings
    from being double-counted as alphanumeric IDs or bare numbers.
    """
    if not text:
        return []

    norm_chars = list(normalize_devanagari_numerals(text))
    tokens: list[str] = []

    def _extract_and_mask(regex: re.Pattern[str], filter_fn=None, is_currency: bool = False) -> None:
        curr_text = "".join(norm_chars)
        for m in regex.finditer(curr_text):
            tok_raw = m.group(0)
            if filter_fn and not filter_fn(tok_raw):
                continue
            if is_currency:
                curr_sym, amt = _parse_currency(tok_raw)
                norm_amt = _normalize_token(amt)
                tokens.append(f"{curr_sym}{norm_amt}")
                tokens.append(norm_amt)
            else:
                tokens.append(_normalize_token(tok_raw))
            for i in range(m.start(), m.end()):
                norm_chars[i] = " "

    # 1. URLs and Emails (highest priority)
    _extract_and_mask(_URL_RE)
    _extract_and_mask(_EMAIL_RE)

    # 2. Statutory IDs
    _extract_and_mask(_STATUTORY_ID_RE)

    # 3. Dates
    _extract_and_mask(_DATE_RE)

    # 4. Alphanumeric IDs
    _extract_and_mask(_ALPHANUMERIC_ID_RE)

    # 5. Percentages (e.g. 5%, 18%, -2.5%)
    _extract_and_mask(_PERCENT_RE)

    # 6. Currency amounts (e.g. Rs. 50, ₹1,50,000, $100)
    _extract_and_mask(_CURRENCY_RE, is_currency=True)

    # 7. Standalone and signed numbers (no digit-length cutoff)
    _extract_and_mask(_NUM_RE)

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
