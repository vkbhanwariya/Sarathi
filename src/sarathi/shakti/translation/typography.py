"""Translation typography compatibility surface.

Shared output font selection and size validation live in ``sarathi.shakti.text.typography``.
Translation historically allows ``normalize_size()`` with no argument, so this module keeps
that call signature while delegating the shared calculation.
"""

from __future__ import annotations

from sarathi.shakti.text.typography import (
    DEFAULT_SIZE_PT,
    DEVANAGARI_FONT,
    ENGLISH_FONT,
    contains_devanagari,
    normalize_size as _normalize_size,
    output_font,
)


def normalize_size(
    size_pt: float | None = None,
    *,
    default_size_pt: float = DEFAULT_SIZE_PT,
) -> float:
    """Preserve Translation's existing optional-argument size-normalization contract."""
    return _normalize_size(size_pt, default_size_pt=default_size_pt)


__all__ = [
    "DEFAULT_SIZE_PT",
    "DEVANAGARI_FONT",
    "ENGLISH_FONT",
    "contains_devanagari",
    "normalize_size",
    "output_font",
]
