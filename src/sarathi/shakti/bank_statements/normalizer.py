"""Financial Value Normalizer for Bank Statements in Sarathi V2.

Normalizes:
- Monetary amounts into Python standard library Decimal (never float)
- Date and optional Time values
- Narration and reference strings
- Debit/Credit direction
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from sarathi.dosh import DoshError, FailureCode

_CURRENCY_SYMBOLS = ["₹", "rs.", "rs", "inr", "$", "usd", "€", "eur", "£", "gbp"]
_DATE_PATTERNS = [
    (re.compile(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$"), "%d/%m/%Y"),
    (re.compile(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$"), "%Y-%m-%d"),
    (re.compile(r"^(\d{1,2})\s+([a-zA-Z]{3,9})\s+(\d{4})$"), "%d %b %Y"),
    (re.compile(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})$"), "%d/%m/%y"),
]


def parse_decimal_amount(raw_val: Any) -> Decimal | None:
    """Parse a raw string, int, or numeric representation into a pure Decimal.

    Handles:
    - Currency symbols (₹, Rs., INR, $)
    - Thousands separators (commas, spaces)
    - Suffix markers (Cr, Dr, /- )
    - Parenthetical negative values (e.g. (1,250.00))
    - Conservative cleaning without float approximation.

    Returns:
        Positive or negative Decimal magnitude, or None if raw_val is empty/None.

    Raises:
        ValueError: If string contains invalid non-monetary characters.
    """
    if raw_val is None:
        return None

    if isinstance(raw_val, Decimal):
        return raw_val

    if isinstance(raw_val, int) and not isinstance(raw_val, bool):
        return Decimal(str(raw_val))

    val_str = str(raw_val).strip()
    if not val_str or val_str in ("-", "--", "NA", "N/A", "nil", "null"):
        return None

    # Check for parenthetical negative (1,250.00)
    is_parenthetical_negative = False
    if val_str.startswith("(") and val_str.endswith(")"):
        is_parenthetical_negative = True
        val_str = val_str[1:-1].strip()

    # Check for Dr/Cr suffixes
    is_dr = False
    is_cr = False
    val_lower = val_str.lower()

    if val_lower.endswith("dr") or val_lower.endswith("dr."):
        is_dr = True
        val_str = re.sub(r"(?i)dr\.?$", "", val_str).strip()
    elif val_lower.endswith("cr") or val_lower.endswith("cr."):
        is_cr = True
        val_str = re.sub(r"(?i)cr\.?$", "", val_str).strip()

    # Remove /- suffix (e.g. 50/-)
    val_str = re.sub(r"/\-+$", "", val_str).strip()

    # Remove currency symbols
    for sym in _CURRENCY_SYMBOLS:
        if val_str.lower().startswith(sym):
            val_str = val_str[len(sym):].strip()
        elif val_str.lower().endswith(sym):
            val_str = val_str[:-len(sym)].strip()

    # Clean whitespace and commas
    val_str = val_str.replace(",", "").replace(" ", "").strip()

    if not val_str:
        return None

    try:
        amount = Decimal(val_str)
    except InvalidOperation as err:
        raise ValueError(f"Failed to parse monetary Decimal amount from {raw_val!r}.") from err

    if is_parenthetical_negative:
        amount = -abs(amount)

    return amount


def parse_date(raw_val: Any) -> date | None:
    """Parse a date string or object into a datetime.date instance."""
    if raw_val is None:
        return None

    if isinstance(raw_val, datetime):
        return raw_val.date()

    if isinstance(raw_val, date):
        return raw_val

    date_str = str(raw_val).strip()
    if not date_str:
        return None

    # Replace dot or space separators
    normalized = date_str.replace(".", "/").replace("-", "/")

    # Standard formats
    for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass

    return None


def parse_time(raw_val: Any) -> time | None:
    """Parse an optional time string into a datetime.time instance."""
    if raw_val is None:
        return None

    if isinstance(raw_val, time):
        return raw_val

    if isinstance(raw_val, datetime):
        return raw_val.time()

    time_str = str(raw_val).strip()
    if not time_str:
        return None

    for fmt in ("%H:%M:%S", "%I:%M:%S %p", "%H:%M", "%I:%M %p"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            pass

    return None
