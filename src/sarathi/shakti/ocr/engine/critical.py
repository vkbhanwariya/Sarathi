"""Consequence-driven Critical Span Detector for OCR verification and retry.

Identifies high-consequence entities (currency, amounts, statutory identifiers,
dates, legal references) where an OCR error carries severe operational or legal impact.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final


class CriticalityType(StrEnum):
    """Classification of high-consequence text tokens."""

    CURRENCY_AMOUNT = "currency_amount"
    STATUTORY_IDENTIFIER = "statutory_identifier"
    DATE = "date"
    ACCOUNT_REFERENCE = "account_reference"
    LEGAL_REFERENCE = "legal_reference"
    PERCENTAGE_RATE = "percentage_rate"


# Default consequence-driven thresholds
DEFAULT_CRITICAL_RETRY_THRESHOLD: Final[float] = 0.85
DEFAULT_CRITICAL_REVIEW_THRESHOLD: Final[float] = 0.90

# 1. Currency and formatted financial amounts
_CURRENCY_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:[₹]|Rs\.?|INR|\bdebited\b|\bcredited\b|\bbalance\b)"
    r"|"
    r"(?:[₹]|Rs\.?|INR)?\s*\b\d{1,2},\d{2},\d{3}(?:,\d{2})*(?:\.\d{1,2})?\b"
    r"|"
    r"(?:[₹]|Rs\.?|INR)?\s*\b\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\b"
    r"|"
    r"\b\d+\.\d{2}\b",
    re.IGNORECASE,
)

# 2. Indian statutory and corporate identifiers
_STATUTORY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"  # PAN
    r"|"
    r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"  # GSTIN
    r"|"
    r"\b[A-Z]{4}0[A-Z0-9]{6}\b"  # IFSC
    r"|"
    r"\b[A-Z]{4}[0-9]{5}[A-Z]\b"  # TAN
    r"|"
    r"\b[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}\b"  # CIN
    r"|"
    r"\b[A-Z]{4}[0-9]{8}[0-9]{4}\b",  # CNR (eCourts 16-char)
)

# 3. Date expressions
_DATE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\b"
    r"|"
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b",
    re.IGNORECASE,
)

# 4. Account, cheque, transaction, and payment references
_ACCOUNT_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:A/C|Acct|Account|Chq|Cheque|Ref|Reference|UTR|Txn|Transaction|NEFT|RTGS|IMPS)[\s.:#-]*\w+",
    re.IGNORECASE,
)

# 5. Legal sections, rules, orders, and statutory acts
_LEGAL_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:Sec(?:tion)?\.?|धारा|Rule|Article|Order|Clause)\s*[\dIVXLCDM]+"
    r"|"
    r"\b(?:FIR|PMLA|CrPC|IPC|BNS|BNSS|BSA|NI\s*Act)\b",
    re.IGNORECASE,
)

# 6. Percentages and interest rates
_PERCENTAGE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent\b|p\.a\.|per\s+annum\b)",
    re.IGNORECASE,
)


def classify_span(text: str) -> tuple[bool, CriticalityType | None]:
    """Classify whether a text span contains high-consequence financial or statutory tokens.

    Args:
        text: Raw text content of the candidate span.

    Returns:
        Tuple of (is_critical, criticality_type).
    """
    clean = text.strip()
    if not clean or len(clean) < 2:
        return False, None

    # 1. Currency / Amount check
    if _CURRENCY_AMOUNT_RE.search(clean):
        return True, CriticalityType.CURRENCY_AMOUNT

    # 2. Statutory ID check
    if _STATUTORY_ID_RE.search(clean):
        return True, CriticalityType.STATUTORY_IDENTIFIER

    # 3. Account / Reference check
    if _ACCOUNT_REF_RE.search(clean):
        return True, CriticalityType.ACCOUNT_REFERENCE

    # 4. Legal / Section reference check
    if _LEGAL_REF_RE.search(clean):
        return True, CriticalityType.LEGAL_REFERENCE

    # 5. Date check
    if _DATE_RE.search(clean):
        return True, CriticalityType.DATE

    # 6. Percentage / Rate check
    if _PERCENTAGE_RE.search(clean):
        return True, CriticalityType.PERCENTAGE_RATE

    return False, None


_LETTER_TO_DIGIT: Final[dict[str, str]] = {
    "O": "0",
    "o": "0",
    "D": "0",
    "Q": "0",
    "I": "1",
    "l": "1",
    "i": "1",
    "S": "5",
    "s": "5",
    "B": "8",
    "Z": "2",
    "z": "2",
}

_DIGIT_TO_LETTER: Final[dict[str, str]] = {
    "0": "O",
    "1": "I",
    "5": "S",
    "8": "B",
    "2": "Z",
}


def repair_critical_token(text: str, crit_type: CriticalityType | None = None) -> tuple[str, bool]:
    """Auto-repair deterministic OCR character confusions in critical spans.

    Gated strictly to high-consequence entities (currency, statutory identifiers, dates, IFSC/UTR).
    Returns:
        tuple of (repaired_text, was_repaired).
    """
    if not text or len(text.strip()) < 2:
        return text, False

    clean = text.strip()
    if crit_type is None:
        is_crit, detected_type = classify_span(clean)
        if not is_crit:
            return text, False
        crit_type = detected_type

    # 1. CURRENCY / FINANCIAL AMOUNT REPAIR
    if crit_type == CriticalityType.CURRENCY_AMOUNT:
        repaired = clean
        # 'O'/'o' between digits or right after decimal / comma / symbol
        repaired = re.sub(r"(?<=\d)[Oo](?=\d|\.|$)", "0", repaired)
        repaired = re.sub(r"(?<=[\.,₹])([Oo])(?=\d)", "0", repaired)
        repaired = re.sub(r"(?<=\.)[Oo]{2}\b", "00", repaired)
        repaired = re.sub(r"(?<=\.)[Oo](?=\d)", "0", repaired)
        repaired = re.sub(r"(?<=\.\d)[Oo]\b", "0", repaired)
        # 'l' or 'I' between digits / commas: e.g. 1,l50 -> 1,150
        repaired = re.sub(r"(?<=[,\d])[lI](?=\d)", "1", repaired)
        # 'S' or 's' between digits / commas: e.g. 1,S00 -> 1,500
        repaired = re.sub(r"(?<=[,\d])[Ss](?=\d)", "5", repaired)
        # 'B' between digits / commas: e.g. 1,B00 -> 1,800
        repaired = re.sub(r"(?<=[,\d])B(?=\d)", "8", repaired)
        if repaired != clean and _CURRENCY_AMOUNT_RE.search(repaired):
            return repaired, True

    # 2. DATE REPAIR
    elif crit_type == CriticalityType.DATE:
        repaired = clean
        # Repair 'O'/'o' in date day/month/year components
        repaired = re.sub(r"\b([Oo])(\d[-./])", r"0\2", repaired)
        repaired = re.sub(r"([-./])([Oo])(\d)", r"\g<1>0\2", repaired)
        repaired = re.sub(r"([-./])(\d)([Oo])\b", r"\g<1>\g<2>0", repaired)
        repaired = re.sub(r"([-./])([Oo]{2})\b", r"\g<1>00", repaired)
        # Repair 'l' in day/month
        repaired = re.sub(r"\b([lI])(\d[-./])", r"1\2", repaired)
        repaired = re.sub(r"([-./])([lI])(\d)", r"\g<1>1\2", repaired)
        if repaired != clean and _DATE_RE.search(repaired):
            return repaired, True

    # 3. STATUTORY IDENTIFIER REPAIR
    elif crit_type == CriticalityType.STATUTORY_IDENTIFIER:
        candidate = re.sub(r"[\s\-_]", "", clean).upper()
        # Check IFSC candidate (11 chars)
        if len(candidate) == 11 and candidate[:4].isalnum():
            from sarathi.shakti.bank_statements.utr_repair import is_valid_ifsc, repair_ifsc

            if not is_valid_ifsc(candidate):
                rep_ifsc, was_rep = repair_ifsc(candidate)
                if was_rep and is_valid_ifsc(rep_ifsc):
                    return rep_ifsc, True

        # Check PAN candidate (10 chars: 5 letters + 4 digits + 1 letter)
        if len(candidate) == 10 and candidate.isalnum():
            from sarathi.shakti.statutory.checksums import verify_pan

            if not verify_pan(candidate):
                chars = list(candidate)
                for i in range(5):
                    if chars[i].isdigit() and chars[i] in _DIGIT_TO_LETTER:
                        chars[i] = _DIGIT_TO_LETTER[chars[i]]
                for i in range(5, 9):
                    if chars[i].isalpha() and chars[i] in _LETTER_TO_DIGIT:
                        chars[i] = _LETTER_TO_DIGIT[chars[i]]
                if chars[9].isdigit() and chars[9] in _DIGIT_TO_LETTER:
                    chars[9] = _DIGIT_TO_LETTER[chars[9]]
                rep_pan = "".join(chars)
                if verify_pan(rep_pan):
                    return rep_pan, True

        # Check GSTIN candidate (15 chars)
        if len(candidate) == 15 and candidate.isalnum():
            from sarathi.shakti.statutory.checksums import calculate_gstin_check_digit, verify_gstin

            if not verify_gstin(candidate):
                chars = list(candidate)
                for i in (0, 1):
                    if chars[i] in _LETTER_TO_DIGIT:
                        chars[i] = _LETTER_TO_DIGIT[chars[i]]
                for i in range(2, 7):
                    if chars[i].isdigit() and chars[i] in _DIGIT_TO_LETTER:
                        chars[i] = _DIGIT_TO_LETTER[chars[i]]
                for i in range(7, 11):
                    if chars[i].isalpha() and chars[i] in _LETTER_TO_DIGIT:
                        chars[i] = _LETTER_TO_DIGIT[chars[i]]
                if chars[11].isdigit() and chars[11] in _DIGIT_TO_LETTER:
                    chars[11] = _DIGIT_TO_LETTER[chars[11]]
                chars[13] = "Z"
                prefix14 = "".join(chars[:14])
                expected_digit = calculate_gstin_check_digit(prefix14)
                if expected_digit is not None:
                    chars[14] = expected_digit
                    rep_gstin = "".join(chars)
                    if verify_gstin(rep_gstin):
                        return rep_gstin, True

    # 4. ACCOUNT / BANKING REFERENCE REPAIR
    elif crit_type == CriticalityType.ACCOUNT_REFERENCE:
        from sarathi.shakti.bank_statements.utr_repair import repair_ifsc, repair_utr

        words = clean.split()
        repaired_words: list[str] = []
        modified = False
        for w in words:
            clean_w = re.sub(r"[\s\-_:/]", "", w).upper()
            if len(clean_w) == 11:
                rep_w, was_rep = repair_ifsc(clean_w)
                if was_rep:
                    repaired_words.append(rep_w)
                    modified = True
                    continue
            if len(clean_w) in (12, 16, 22):
                rep_w, _, was_rep = repair_utr(clean_w)
                if was_rep:
                    repaired_words.append(rep_w)
                    modified = True
                    continue
            repaired_words.append(w)
        if modified:
            return " ".join(repaired_words), True

    return text, False


def validate_critical_token(text: str, crit_type: CriticalityType | None = None) -> tuple[bool, str | None]:
    """Validate whether a critical token strictly complies with domain rules and checksums.

    Returns:
        tuple of (is_valid, validation_label_or_reason).
    """
    clean = text.strip()
    if not clean:
        return False, "empty"

    if crit_type is None:
        is_crit, detected_type = classify_span(clean)
        if not is_crit:
            return True, None
        crit_type = detected_type

    if crit_type == CriticalityType.CURRENCY_AMOUNT:
        if _CURRENCY_AMOUNT_RE.search(clean):
            return True, "valid_amount"
        return False, "invalid_amount_format"

    if crit_type == CriticalityType.DATE:
        if _DATE_RE.search(clean):
            return True, "valid_date"
        return False, "invalid_date_format"

    if crit_type == CriticalityType.STATUTORY_IDENTIFIER:
        candidate = re.sub(r"[\s\-_]", "", clean).upper()
        if len(candidate) == 10:
            from sarathi.shakti.statutory.checksums import verify_pan

            if verify_pan(candidate):
                return True, "valid_pan"
        elif len(candidate) == 15:
            from sarathi.shakti.statutory.checksums import verify_gstin

            if verify_gstin(candidate):
                return True, "valid_gstin"
        elif len(candidate) == 11:
            from sarathi.shakti.bank_statements.utr_repair import is_valid_ifsc

            if is_valid_ifsc(candidate):
                return True, "valid_ifsc"
        elif len(candidate) == 21:
            from sarathi.shakti.statutory.checksums import verify_cin

            if verify_cin(candidate):
                return True, "valid_cin"
        return False, "unverified_statutory_identifier"

    return True, None


__all__ = [
    "DEFAULT_CRITICAL_RETRY_THRESHOLD",
    "DEFAULT_CRITICAL_REVIEW_THRESHOLD",
    "CriticalityType",
    "classify_span",
    "repair_critical_token",
    "validate_critical_token",
]
