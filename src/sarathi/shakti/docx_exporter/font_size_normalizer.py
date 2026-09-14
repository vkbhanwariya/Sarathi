"""Pair-aware Visual Font-Size Normalization for DOCX Exporter.

Owns visual point-size compensation between anchor and target fonts:
- FontSizeAdjustment: Immutable adjustment rule (scale + offset).
- Pair-specific calibration lookup table.
- Font name normalization.
- Safe identity fallback for uncalibrated font pairs.

Does not own character conversion, profile detection, or XML serialization.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FontSizeAdjustment:
    """Pair-specific visual font-size adjustment formula."""

    scale: float = 1.0
    offset_pt: float = 0.0

    def apply(self, size_pt: float) -> float:
        """Apply visual scale and offset to logical size in points."""
        if size_pt <= 0:
            raise ValueError("font size must be greater than zero")
        return size_pt * self.scale + self.offset_pt


def normalize_font_name(font_name: str) -> str:
    """Normalize font family name defensively for dictionary lookup."""
    if not isinstance(font_name, str):
        return ""
    return " ".join(font_name.strip().casefold().split())


# Calibrated production ratios:
# Legacy 8-bit Devanagari typewriter fonts (Kruti Dev, DevLys) typed at 16 pt body text
# dynamically map to modern 12 pt baseline (scale = 12/16 = 0.75, offset = 0.0 pt).
# Headings scale proportionally (e.g. 24 pt -> 18 pt, 20 pt -> 15 pt), preserving hierarchy.
_LEGACY_TO_MODERN_SCALE: float = 12.0 / 16.0  # 0.75
_MODERN_TO_LEGACY_SCALE: float = 16.0 / 12.0  # ~1.3333

_LEGACY_PREFIXES: tuple[str, ...] = (
    "kruti",
    "krutidev",
    "devlys",
    "walkman",
    "chanakya",
    "shree-dev",
    "shreedev",
    "aps-c-dv",
    "aps",
    "shivaji",
)

_MODERN_PREFIXES: tuple[str, ...] = (
    "nirmala",
    "times",
    "mangal",
    "calibri",
    "arial",
    "bookman",
    "aparajita",
    "kokila",
    "utsaah",
    "cambria",
    "georgia",
)


def _is_legacy_hindi(name: str) -> bool:
    return any(pfx in name for pfx in _LEGACY_PREFIXES)


def _is_modern(name: str) -> bool:
    return any(pfx in name for pfx in _MODERN_PREFIXES)


_PAIR_ADJUSTMENTS: dict[tuple[str, str], FontSizeAdjustment] = {
    ("kruti dev 010", "nirmala ui"): FontSizeAdjustment(scale=_LEGACY_TO_MODERN_SCALE, offset_pt=0.0),
    ("kruti dev 010", "times new roman"): FontSizeAdjustment(scale=_LEGACY_TO_MODERN_SCALE, offset_pt=0.0),
    ("devlys 010", "nirmala ui"): FontSizeAdjustment(scale=_LEGACY_TO_MODERN_SCALE, offset_pt=0.0),
    ("devlys 010", "times new roman"): FontSizeAdjustment(scale=_LEGACY_TO_MODERN_SCALE, offset_pt=0.0),
    ("nirmala ui", "kruti dev 010"): FontSizeAdjustment(scale=_MODERN_TO_LEGACY_SCALE, offset_pt=0.0),
    ("times new roman", "kruti dev 010"): FontSizeAdjustment(scale=_MODERN_TO_LEGACY_SCALE, offset_pt=0.0),
    ("nirmala ui", "devlys 010"): FontSizeAdjustment(scale=_MODERN_TO_LEGACY_SCALE, offset_pt=0.0),
    ("times new roman", "devlys 010"): FontSizeAdjustment(scale=_MODERN_TO_LEGACY_SCALE, offset_pt=0.0),
    ("nirmala ui", "times new roman"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("times new roman", "nirmala ui"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("kruti dev 010", "utsaah"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("devlys 010", "utsaah"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("utsaah", "kruti dev 010"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("utsaah", "devlys 010"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("utsaah", "nirmala ui"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("nirmala ui", "utsaah"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("utsaah", "times new roman"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
    ("times new roman", "utsaah"): FontSizeAdjustment(scale=1.0, offset_pt=0.0),
}


def get_font_size_adjustment(
    *,
    anchor_font: str,
    target_font: str,
) -> FontSizeAdjustment:
    """Retrieve the pair-specific FontSizeAdjustment, applying family heuristics and safe fallback."""
    norm_anchor = normalize_font_name(anchor_font)
    norm_target = normalize_font_name(target_font)

    if (norm_anchor, norm_target) in _PAIR_ADJUSTMENTS:
        return _PAIR_ADJUSTMENTS[(norm_anchor, norm_target)]

    # Dynamic family-level matching
    if _is_legacy_hindi(norm_anchor) and _is_modern(norm_target):
        return FontSizeAdjustment(scale=_LEGACY_TO_MODERN_SCALE, offset_pt=0.0)

    if _is_modern(norm_anchor) and _is_legacy_hindi(norm_target):
        return FontSizeAdjustment(scale=_MODERN_TO_LEGACY_SCALE, offset_pt=0.0)

    if _is_modern(norm_anchor) and _is_modern(norm_target):
        return FontSizeAdjustment(scale=1.0, offset_pt=0.0)

    return FontSizeAdjustment(scale=1.0, offset_pt=0.0)


def normalize_font_size(
    size_pt: float,
    *,
    anchor_font: str,
    target_font: str,
) -> float:
    """Calculate the visually normalized target font size in points given an anchor font."""
    adjustment = get_font_size_adjustment(
        anchor_font=anchor_font,
        target_font=target_font,
    )
    return adjustment.apply(size_pt)
