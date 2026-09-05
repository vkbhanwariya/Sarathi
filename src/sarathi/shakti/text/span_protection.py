"""Span Protection and Restoration Utilities for Shakti.

Guarantees non-translatable or non-convertible spans (URLs, emails, dates, monetary
amounts, numbers, percentages, alphanumeric IDs, and Unicode Devanagari text)
survive pipeline operations untouched.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

_PROT_START: str = "\ue000"
_PROT_END: str = "\ue001"

_URL_RE: re.Pattern[str] = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE: re.Pattern[str] = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
_UNICODE_DEVANAGARI_RE: re.Pattern[str] = re.compile(r"[\u0900-\u097F]+(?:[\s\u0900-\u097F]*[\u0900-\u097F])?")
_DATE_RE: re.Pattern[str] = re.compile(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b")
_NUM_RE: re.Pattern[str] = re.compile(r"(?:Rs\.?|₹|\$|€|£)?\s*\b\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\s*%?\b")
_PERCENT_RE: re.Pattern[str] = re.compile(r"\b\d+%\b|\(\d+%\)")
_ID_RE: re.Pattern[str] = re.compile(r"\b[A-Z0-9_-]{4,}\b")


class BaseSpanProtector:
    """Base engine for protecting and restoring non-translatable or non-convertible spans."""

    @staticmethod
    def format_placeholder(index: int) -> str:
        """Format unique Private-Use-Area placeholder for protected span index."""
        return f"{_PROT_START}{chr(0xE100 + index)}{_PROT_END}"

    def restore(self, text: str, spans: Sequence[Any]) -> str:
        """Restore all protected spans from placeholders byte-for-byte."""
        for s in spans:
            text = text.replace(s.placeholder, s.original_text)
        return text
