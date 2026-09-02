"""Financial Value Normalizer for Bank Statements in Sarathi V2.

DEPRECATED: Use sarathi.shakti.bank_statements.converter instead.
"""

from __future__ import annotations

import warnings
from datetime import date, time
from decimal import Decimal
from typing import Any

from sarathi.shakti.bank_statements.converter import (
    parse_date as _parse_date,
)
from sarathi.shakti.bank_statements.converter import (
    parse_decimal_amount as _parse_decimal_amount,
)
from sarathi.shakti.bank_statements.converter import (
    parse_time as _parse_time,
)


def parse_decimal_amount(raw_val: Any) -> Decimal | None:
    warnings.warn(
        "normalizer.parse_decimal_amount is deprecated; use converter.parse_decimal_amount instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _parse_decimal_amount(raw_val)


def parse_date(raw_val: Any) -> date | None:
    warnings.warn(
        "normalizer.parse_date is deprecated; use converter.parse_date instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _parse_date(raw_val)


def parse_time(raw_val: Any) -> time | None:
    warnings.warn(
        "normalizer.parse_time is deprecated; use converter.parse_time instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _parse_time(raw_val)


__all__ = ["parse_date", "parse_decimal_amount", "parse_time"]
