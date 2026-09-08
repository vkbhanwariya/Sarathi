"""Fast heuristic detector for statutory, tax, corporate, and legal documents."""

from __future__ import annotations

import re
from typing import Any

from sarathi.shakti.statutory.checksums import (
    CIN_PATTERN,
    CNR_PATTERN,
    GSTIN_PATTERN,
    PAN_PATTERN,
)
from sarathi.shakti.statutory.models import StatutoryDocumentType

_STATUTORY_KEYWORDS = re.compile(
    r"\b(GSTIN|INVOICE|TAX\s*INVOICE|E-WAY\s*BILL|INCOME\s*TAX|ASSESSMENT\s*YEAR|"
    r"PERMANENT\s*ACCOUNT\s*NUMBER|FORM\s*16|MINISTRY\s*OF\s*CORPORATE\s*AFFAIRS|"
    r"REGISTRAR\s*OF\s*COMPANIES|CIN|LLPIN|HIGH\s*COURT|SUPREME\s*COURT|DISTRICT\s*COURT|"
    r"VERSUS|PETITIONER|RESPONDENT|CNR\s*NO)\b",
    re.IGNORECASE,
)


def is_statutory_document(text: str) -> tuple[bool, StatutoryDocumentType, float]:
    """Determine whether text contains statutory or legal document signatures."""
    if not text or len(text.strip()) < 20:
        return False, StatutoryDocumentType.UNKNOWN, 0.0

    matches = _STATUTORY_KEYWORDS.findall(text[:8192])
    match_count = len(matches)

    if match_count == 0:
        return False, StatutoryDocumentType.UNKNOWN, 0.0

    # Look for key identifiers
    has_gstin = bool(re.search(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b", text))
    has_pan = bool(re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text))
    has_cin = bool(re.search(r"\b[LU][0-9]{5}[A-Z]{2}[1-2][0-9]{3}[A-Z]{3}[0-9]{6}\b", text))
    has_cnr = bool(re.search(r"\b[A-Z]{4}[0-9]{12}\b", text))

    if has_gstin:
        return True, StatutoryDocumentType.GST_INVOICE, min(0.6 + match_count * 0.05, 0.98)
    if has_cin:
        return True, StatutoryDocumentType.MCA_FILING, min(0.6 + match_count * 0.05, 0.98)
    if has_cnr:
        return True, StatutoryDocumentType.ECOURTS_ORDER, min(0.6 + match_count * 0.05, 0.98)
    if has_pan and "INCOME TAX" in text.upper():
        return True, StatutoryDocumentType.INCOME_TAX_ACK, min(0.6 + match_count * 0.05, 0.95)

    if match_count >= 2:
        return True, StatutoryDocumentType.UNKNOWN, min(0.4 + match_count * 0.05, 0.85)

    return False, StatutoryDocumentType.UNKNOWN, 0.0
