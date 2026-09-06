"""Pair-aware Visual Font-Size Normalization for Roopa Font Conversion.

Re-exports domain-neutral font-size normalization primitives from
``sarathi.shakti.docx_exporter.font_size_normalizer`` for backward compatibility.
"""

from __future__ import annotations

from sarathi.shakti.docx_exporter.font_size_normalizer import (
    FontSizeAdjustment,
    get_font_size_adjustment,
    normalize_font_name,
    normalize_font_size,
)

__all__ = [
    "FontSizeAdjustment",
    "get_font_size_adjustment",
    "normalize_font_name",
    "normalize_font_size",
]
