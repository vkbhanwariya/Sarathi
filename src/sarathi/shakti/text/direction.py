"""Shared language direction normalization for Shakti translation capabilities."""

from __future__ import annotations

from typing import NamedTuple


class NormalizedDirection(NamedTuple):
    """Normalized translation direction codes and names."""

    source_code: str  # e.g. 'en', 'hi'
    target_code: str  # e.g. 'hi', 'en'
    source_name: str  # e.g. 'English', 'Hindi'
    target_name: str  # e.g. 'Hindi', 'English'
    direction_key: str  # e.g. 'en-hi', 'hi-en'


_LANGUAGE_NAMES: dict[str, str] = {
    "hi": "Hindi",
    "en": "English",
    "auto": "the source language",
}


def normalize_translation_direction(raw: str | None, default: str = "hi-en") -> NormalizedDirection:
    """Normalize user or UI supplied translation direction strings reliably.

    Handles:
    - 'hi_en', 'en_hi' (UI App.tsx format)
    - 'hi-en', 'en-hi' (hyphenated standard)
    - 'hi_to_en', 'en_to_hi' (verbose)
    - 'auto-en', 'auto-hi'
    """
    if not raw or not isinstance(raw, str):
        val = default
    else:
        val = raw.strip().lower()

    val = val.replace("->", "-").replace("_to_", "-").replace("-to-", "-").replace("_", "-")
    while "--" in val:
        val = val.replace("--", "-")

    if val in ("hi-en", "hien"):
        return NormalizedDirection("hi", "en", "Hindi", "English", "hi-en")
    if val in ("en-hi", "enhi"):
        return NormalizedDirection("en", "hi", "English", "Hindi", "en-hi")
    if val in ("auto-en", "autoen"):
        return NormalizedDirection("auto", "en", "the source language", "English", "auto-en")
    if val in ("auto-hi", "autohi"):
        return NormalizedDirection("auto", "hi", "the source language", "Hindi", "auto-hi")

    # Generic delimiter fallback
    parts = val.split("-")
    src = parts[0].strip() if len(parts) > 0 and parts[0].strip() else "hi"
    tgt = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "en"
    src_name = _LANGUAGE_NAMES.get(src, src.capitalize())
    tgt_name = _LANGUAGE_NAMES.get(tgt, tgt.capitalize())
    return NormalizedDirection(src, tgt, src_name, tgt_name, f"{src}-{tgt}")
