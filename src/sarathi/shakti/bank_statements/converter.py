"""Financial Value Converter for Bank Statements in Sarathi.

Converts monetary amounts into Python Decimal (never float), dates, and times.
Canonical module for value conversion in Shakti bank statements.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

_DATE_FORMATS = (
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%d/%m/%y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y-%m-%d",
    "%d%m%Y",
)
_TIME_FORMATS = ("%H:%M:%S", "%I:%M:%S %p", "%H:%M", "%I:%M %p")
_NULL_WORDS = frozenset(("", "-", "--", "na", "n/a", "nil", "null", "'", '"'))
_CURRENCY_PREFIX_RE = re.compile(r"^(?:[₹$€£]|rs\.?|inr|usd|eur|gbp)\s*", re.IGNORECASE)
_SUFFIX_RE = re.compile(r"(?:\s*(?:\(?\s*(?:dr\.?|cr\.?|od)\s*\)?)|/\-+)$", re.IGNORECASE)
_DR_BALANCE_RE = re.compile(r"(?:\b|\s|\()(?:dr\.?|od)(?:\b|\s|\)|\.|$)", re.IGNORECASE)
_CR_BALANCE_RE = re.compile(r"(?:\b|\s|\()cr\.?(?:\b|\s|\)|\.|$)", re.IGNORECASE)


def parse_balance_amount(raw_val: Any) -> Decimal | None:
    """Parse a running, opening, or closing balance preserving Dr (negative/overdraft) and Cr (positive) signs."""
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
            if not val_str or val_str.lower() in _NULL_WORDS:
                return None
            has_dr = bool(_DR_BALANCE_RE.search(val_str))
            has_cr = bool(_CR_BALANCE_RE.search(val_str))

            parsed = parse_decimal_amount(val_str)
            if parsed is None:
                return None

            if has_dr and not has_cr:
                return -abs(parsed)
            elif has_cr and not has_dr:
                return abs(parsed)
            return parsed
        case _:
            return parse_balance_amount(str(raw_val))


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
            if not val_str or val_str.lower() in _NULL_WORDS:
                return None

            is_negative = val_str.startswith("(") and val_str.endswith(")")
            if is_negative:
                val_str = val_str[1:-1].strip()
            elif val_str.startswith("-"):
                is_negative = True
                val_str = val_str[1:].strip()

            val_str = _CURRENCY_PREFIX_RE.sub("", val_str).strip()
            val_str = _SUFFIX_RE.sub("", val_str).strip()

            if val_str.endswith("-"):
                is_negative = True
                val_str = val_str[:-1].strip()

            # Remove standard thousand separators
            val_str = val_str.replace(",", "")
            # Allow standard 3-digit thousand grouping spaces (e.g. "1 250.50"), while rejecting ambiguous spaces ("5 0")
            if re.match(r"^\d{1,3}(?:\s\d{3})+(?:\.\d+)?$", val_str):
                val_str = val_str.replace(" ", "")
            if not val_str:
                return None

            try:
                amt = Decimal(val_str)
                return -amt if is_negative else amt
            except InvalidOperation:
                # Per Bank Veda: failed parsing stays unresolved / None, never silently converted or raised
                return None
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
            date_str = raw_val.strip().replace("\n", "").replace("\xa0", " ").strip("\"'")
            if not date_str:
                return None
            try:
                # Direct ISO / datetime string parsing (e.g. '2025-01-01 00:00:00', '2025-01-01T00:00:00', '2025-01-01')
                return datetime.fromisoformat(date_str).date()
            except ValueError:
                pass
            normalized = date_str.replace(".", "/").replace("-", "/")
            candidates = [date_str, normalized]
            if ":" in date_str:
                # String contains time component (e.g. '15/01/2025 14:30:00')
                first_part = date_str.split()[0]
                candidates.extend([first_part, first_part.replace(".", "/").replace("-", "/")])
            for candidate in candidates:
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
            try:
                if " " in time_str or "T" in time_str:
                    return datetime.fromisoformat(time_str).time()
            except ValueError:
                pass
            candidates = [time_str]
            if " " in time_str:
                candidates.append(time_str.split()[-1])
            for candidate in candidates:
                for fmt in _TIME_FORMATS:
                    try:
                        return datetime.strptime(candidate, fmt).time()
                    except ValueError:
                        pass
            return None
        case _:
            return None
