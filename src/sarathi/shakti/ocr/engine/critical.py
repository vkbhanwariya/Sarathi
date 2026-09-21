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
