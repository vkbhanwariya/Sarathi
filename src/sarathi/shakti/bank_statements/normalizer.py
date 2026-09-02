"""Financial Value Normalizer for Bank Statements in Sarathi V2.

Normalizes monetary amounts into Python Decimal (never float), dates, and times.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

_DATE_FORMATS = (
    "%d/%m/%Y", "%Y/%m/%d", "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"
)
_TIME_FORMATS = ("%H:%M:%S", "%I:%M:%S %p", "%H:%M", "%I:%M %p")
_NULL_WORDS = frozenset(("", "-", "--", "na", "n/a", "nil", "null"))
_CLEAN_AMT_RE = re.compile(r"^[₹$€£]|rs\.?|inr|usd|eur|gbp|[,\s()]|/\-+$|dr\.?$|cr\.?$", re.IGNORECASE)


def parse_decimal_amount(raw_val: Any) -> Decimal | None:
    """Parse a raw value into a pure Decimal without float arithmetic."""
    match raw_val:
        case None:
            return None
        case bool():
            return None
        case Decimal():
            return raw_val
        case int():
            return Decimal(str(raw_val))
        case str():
            val_str = raw_val.strip()
            if val_str.lower() in _NULL_WORDS:
                return None

            is_negative = val_str.startswith("(") and val_str.endswith(")")
            cleaned_num = _CLEAN_AMT_RE.sub("", val_str).strip()
            if not cleaned_num:
                return None

            try:
                amt = Decimal(cleaned_num)
                return -amt if is_negative else amt
            except InvalidOperation as err:
                raise ValueError(f"Failed to parse monetary Decimal amount from {raw_val!r}.") from err
        case _:
            return parse_decimal_amount(str(raw_val))


def parse_date(raw_val: Any) -> date | None:
    """Parse a date string or object into a datetime.date instance."""
    match raw_val:
        case None:
            return None
        case datetime():
            return raw_val.date()
        case date():
            return raw_val
        case str():
            date_str = raw_val.strip()
            if not date_str:
                return None
            normalized = date_str.replace(".", "/").replace("-", "/")
            for candidate in (date_str, normalized):
                for fmt in _DATE_FORMATS:
                    try:
                        return datetime.strptime(candidate, fmt).date()
                    except ValueError:
                        pass
            return None
        case _:
            return None


def parse_time(raw_val: Any) -> time | None:
    """Parse an optional time string into a datetime.time instance."""
    match raw_val:
        case None:
            return None
        case time():
            return raw_val
        case datetime():
            return raw_val.time()
        case str():
            time_str = raw_val.strip()
            if not time_str:
                return None
            for fmt in _TIME_FORMATS:
                try:
                    return datetime.strptime(time_str, fmt).time()
                except ValueError:
                    pass
            return None
        case _:
            return None
