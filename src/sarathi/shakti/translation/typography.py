"""Translation typography compatibility surface.

Shared output font selection and size validation live in ``sarathi.shakti.text.typography``.
"""

from __future__ import annotations

from sarathi.shakti.text.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    contains_devanagari,
    normalize_size,
    output_font,
)

__all__ = [
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "ENGLISH_FONT",
    "contains_devanagari",
    "normalize_size",
    "output_font",
]
