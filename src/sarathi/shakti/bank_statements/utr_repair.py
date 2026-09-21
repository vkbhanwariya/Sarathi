"""Banking Identifier Syntax Extraction, OCR Auto-Repair, and Balance Integrity.

Enforces RBI transaction reference syntax (NEFT, RTGS, IMPS, UPI, IFSC),
auto-repairs deterministic OCR character confusions (0/O, 1/I, 5/S, 8/B),
and performs mathematical double-entry balance verification with exact row references.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

# RBI IFSC Regex: 4 alphabetic bank code, 5th character strictly '0', 6 alphanumeric branch code
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

# RBI UTR Regexes
_NEFT_RE = re.compile(r"^[A-Z]{4}[0-9]{12}$")
_RTGS_RE = re.compile(r"^[A-Z]{4}[R0-9][0-9]{17}$")
_IMPS_UPI_RE = re.compile(r"^[0-9]{12}$")

# Character confusion mappings
_DIGIT_TO_LETTER = {
    "0": "O",
    "1": "I",
    "5": "S",
    "8": "B",
    "2": "Z",
}

_LETTER_TO_DIGIT = {
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


@dataclass(frozen=True, slots=True)
class BalanceDiscrepancy:
    """Detailed mathematical variance report for a single statement row."""

    row_index: int
    previous_balance: Decimal
    credit: Decimal
    debit: Decimal
    actual_balance: Decimal
    expected_balance: Decimal
    variance: Decimal


def is_valid_ifsc(code: str) -> bool:
    """Return True if code is a strictly valid 11-character RBI IFSC."""
    clean = code.strip().upper()
    return bool(_IFSC_RE.match(clean))


def repair_ifsc(raw_ifsc: str) -> tuple[str, bool]:
    """Auto-repair OCR confusion in an 11-character IFSC code.

    Rules:
      - Positions 1-4: Bank code MUST be letters (e.g. 0->O, 1->I, 5->S, 8->B).
      - Position 5: Reserved character MUST be zero '0' (e.g. O/D/Q -> 0).
      - Positions 6-11: Branch code (alphanumeric).
    """
    clean = re.sub(r"[\s\-_]", "", raw_ifsc).upper()
    if len(clean) != 11:
        return clean, False

    chars = list(clean)
    repaired = False

    # 1. Bank code (positions 1-4)
    for i in range(4):
        if chars[i].isdigit() and chars[i] in _DIGIT_TO_LETTER:
            chars[i] = _DIGIT_TO_LETTER[chars[i]]
            repaired = True

    # 2. 5th character (position 5) strictly '0'
    if chars[4] != "0":
        if chars[4] in _LETTER_TO_DIGIT:
            chars[4] = "0"
            repaired = True
        elif not chars[4].isdigit():
            chars[4] = "0"
            repaired = True

    result = "".join(chars)
    if is_valid_ifsc(result):
        return result, repaired

    return clean, False


def repair_utr(raw_utr: str, tx_type: str | None = None) -> tuple[str, str | None, bool]:
    """Auto-repair OCR confusion in banking UTR strings.

    Returns:
        tuple[repaired_utr, detected_type, was_repaired]
    """
    clean = re.sub(r"[\s\-_:/]", "", raw_utr).upper()
    length = len(clean)

    # 1. IMPS or UPI (12 digits)
    if length == 12 and (tx_type in ("IMPS", "UPI") or not clean[:4].isalpha()):
        chars = list(clean)
        repaired = False
        for i in range(12):
            if chars[i] in _LETTER_TO_DIGIT:
                chars[i] = _LETTER_TO_DIGIT[chars[i]]
                repaired = True
        res = "".join(chars)
        if _IMPS_UPI_RE.match(res):
            det = tx_type if tx_type in ("IMPS", "UPI") else "UPI"
            return res, det, repaired

    # 2. NEFT (16 characters: 4 letters + 12 digits)
    if length == 16:
        chars = list(clean)
        repaired = False
        for i in range(4):
            if chars[i].isdigit() and chars[i] in _DIGIT_TO_LETTER:
                chars[i] = _DIGIT_TO_LETTER[chars[i]]
                repaired = True
        for i in range(4, 16):
            if chars[i] in _LETTER_TO_DIGIT:
                chars[i] = _LETTER_TO_DIGIT[chars[i]]
                repaired = True
        res = "".join(chars)
        if _NEFT_RE.match(res):
            return res, "NEFT", repaired

    # 3. RTGS (22 characters: 4 letters + 'R'/'0-9' + 17 digits)
    if length == 22:
        chars = list(clean)
        repaired = False
        for i in range(4):
            if chars[i].isdigit() and chars[i] in _DIGIT_TO_LETTER:
                chars[i] = _DIGIT_TO_LETTER[chars[i]]
                repaired = True
        for i in range(5, 22):
            if chars[i] in _LETTER_TO_DIGIT:
                chars[i] = _LETTER_TO_DIGIT[chars[i]]
                repaired = True
        res = "".join(chars)
        if _RTGS_RE.match(res):
            return res, "RTGS", repaired

    return clean, tx_type, False


def verify_mathematical_double_entry_balance(
    rows: Sequence[tuple[Decimal | None, Decimal | None, Decimal | None]],
    tolerance: Decimal = Decimal("0.01"),
) -> list[BalanceDiscrepancy]:
    """Verify B_i = B_{i-1} + C_i - D_i across sequential statement rows."""
    discrepancies: list[BalanceDiscrepancy] = []

    for i in range(1, len(rows)):
        prev_bal = rows[i - 1][2]
        crd = rows[i][0] or Decimal("0")
        deb = rows[i][1] or Decimal("0")
        actual_bal = rows[i][2]

        if prev_bal is None or actual_bal is None:
            continue

        expected_bal = prev_bal + crd - deb
        variance = actual_bal - expected_bal

        if abs(variance) > tolerance:
            discrepancies.append(
                BalanceDiscrepancy(
                    row_index=i,
                    previous_balance=prev_bal,
                    credit=crd,
                    debit=deb,
                    actual_balance=actual_bal,
                    expected_balance=expected_bal,
                    variance=variance,
                )
            )

    return discrepancies
