"""Table text processing helpers."""

from __future__ import annotations

from typing import Any


def cell_text(value: Any) -> str:
    """Normalize table cell value to string, mapping None to empty string and trimming whitespace."""
    if value is None:
        return ""
    return str(value).strip()
