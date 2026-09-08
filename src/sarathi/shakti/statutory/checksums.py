"""Checksum and statutory identifier validation algorithms."""

from __future__ import annotations

import re

# Standard regex patterns
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
TAN_PATTERN = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CIN_PATTERN = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[1-2][0-9]{3}[A-Z]{3}[0-9]{6}$")
CNR_PATTERN = re.compile(r"^[A-Z]{4}[0-9]{12}$")
DIN_PATTERN = re.compile(r"^[0-9]{8}$")
IRN_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")

VALID_PAN_TYPES = frozenset({"P", "C", "H", "F", "A", "T", "B", "L", "J", "G"})

VALID_STATE_CODES = frozenset(
    {f"{i:02d}" for i in range(1, 39)} | {"97", "99"}
)

VALID_INDIAN_STATES = frozenset({
    "AP", "AR", "AS", "BR", "CG", "CH", "DD", "DL", "DN", "GA",
    "GJ", "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MH",
    "ML", "MN", "MP", "MZ", "NL", "OD", "OR", "PB", "PY", "RJ",
    "SK", "TG", "TN", "TR", "UP", "UT", "WB",
})

VALID_CIN_OWNERSHIPS = frozenset({
    "PTC", "PLC", "GOI", "NPL", "ULL", "SGC", "FTC", "GAP", "OPC",
})

# Base 36 characters for GSTIN Luhn Mod-36
_CHARS_36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_CHAR_TO_VAL = {c: i for i, c in enumerate(_CHARS_36)}


def verify_pan(pan: str | None) -> bool:
    """Validate 10-character Permanent Account Number format and entity type code."""
    if not pan or not isinstance(pan, str):
        return False
    clean = pan.strip().upper()
    if not PAN_PATTERN.match(clean):
        return False
    entity_code = clean[3]
    return entity_code in VALID_PAN_TYPES


def verify_tan(tan: str | None) -> bool:
    """Validate 10-character Tax Deduction and Collection Account Number format."""
    if not tan or not isinstance(tan, str):
        return False
    clean = tan.strip().upper()
    return bool(TAN_PATTERN.match(clean))


def calculate_gstin_check_digit(gstin_14: str) -> str | None:
    """Calculate the 15th checksum character of a 14-character GSTIN prefix using Luhn Mod-36."""
    if len(gstin_14) != 14:
        return None
    total = 0
    for idx, ch in enumerate(gstin_14):
        if ch not in _CHAR_TO_VAL:
            return None
        val = _CHAR_TO_VAL[ch]
        # Multiplier alternates 1, 2
        factor = 2 if (idx % 2 == 1) else 1
        product = val * factor
        total += (product // 36) + (product % 36)
    check_val = (36 - (total % 36)) % 36
    return _CHARS_36[check_val]


def verify_gstin(gstin: str | None) -> bool:
    """Validate 15-character Goods and Services Tax Identification Number and its checksum."""
    if not gstin or not isinstance(gstin, str):
        return False
    clean = gstin.strip().upper()
    if not GSTIN_PATTERN.match(clean):
        return False

    state_code = clean[:2]
    if state_code not in VALID_STATE_CODES:
        return False

    embedded_pan = clean[2:12]
    if not verify_pan(embedded_pan):
        return False

    if clean[13] != "Z":
        return False

    expected_check = calculate_gstin_check_digit(clean[:14])
    return expected_check == clean[14]


def verify_cin(cin: str | None) -> bool:
    """Validate 21-character Corporate Identity Number syntax, state, year, and ownership."""
    if not cin or not isinstance(cin, str):
        return False
    clean = cin.strip().upper()
    if not CIN_PATTERN.match(clean):
        return False

    state_code = clean[6:8]
    if state_code not in VALID_INDIAN_STATES:
        return False

    year = int(clean[8:12])
    if year < 1850 or year > 2035:
        return False

    ownership = clean[12:15]
    return ownership in VALID_CIN_OWNERSHIPS


def verify_cnr(cnr: str | None) -> bool:
    """Validate 16-character eCourts Case Natural Record format."""
    if not cnr or not isinstance(cnr, str):
        return False
    clean = cnr.strip().upper().replace("-", "")
    return bool(CNR_PATTERN.match(clean))


def verify_din(din: str | None) -> bool:
    """Validate 8-digit Director Identification Number."""
    if not din or not isinstance(din, str):
        return False
    clean = din.strip()
    return bool(DIN_PATTERN.match(clean))
