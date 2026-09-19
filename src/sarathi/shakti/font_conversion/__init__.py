"""Roopa Font Conversion Capability Package for Sarathi."""

from __future__ import annotations

from typing import Any

from sarathi.shakti.font_conversion.models import (
    ConversionCandidate,
    ConversionDecision,
    ConversionMetrics,
    ConversionPlan,
    ConvertedDocumentResult,
    FontConversionResult,
    FontEvidence,
    LegacyFontProfile,
    LogicalRun,
    ProtectedSpan,
)
from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "FontConversionCapability",
    "FontConverter",
    "LegacyFontDetector",
    "ConversionCandidate",
    "ConversionDecision",
    "ConversionMetrics",
    "ConversionPlan",
    "ConvertedDocumentResult",
    "FontConversionResult",
    "FontEvidence",
    "LegacyFontProfile",
    "LogicalRun",
    "ProtectedSpan",
    "CAPABILITY_DECLARATION",
    "PLUGIN_INFO",
    "TextProtector",
    "FontConversionValidator",
    "normalize_macroman_bytes",
    "BinaryFontMetadata",
    "inspect_font_bytes",
    "compute_cmap_signature",
    "compute_anchor_outline_hashes",
    "DEFAULT_ANCHOR_SYMBOLS",
    "VisualFontResolver",
    "VisualFontCandidate",
    "VisualFontEvidence",
]


def __getattr__(name: str) -> Any:
    if name in ("VisualFontResolver", "VisualFontCandidate", "VisualFontEvidence"):
        from sarathi.shakti.font_conversion import visual_resolver

        return getattr(visual_resolver, name)
    if name == "BinaryFontMetadata":
        from sarathi.shakti.font_conversion.font_inspector import BinaryFontMetadata

        return BinaryFontMetadata
    if name == "inspect_font_bytes":
        from sarathi.shakti.font_conversion.font_inspector import inspect_font_bytes

        return inspect_font_bytes
    if name == "compute_cmap_signature":
        from sarathi.shakti.font_conversion.font_inspector import compute_cmap_signature

        return compute_cmap_signature
    if name == "compute_anchor_outline_hashes":
        from sarathi.shakti.font_conversion.font_inspector import compute_anchor_outline_hashes

        return compute_anchor_outline_hashes
    if name == "DEFAULT_ANCHOR_SYMBOLS":
        from sarathi.shakti.font_conversion.font_inspector import DEFAULT_ANCHOR_SYMBOLS

        return DEFAULT_ANCHOR_SYMBOLS
    if name == "normalize_macroman_bytes":
        from sarathi.shakti.font_conversion.byte_normalizer import normalize_macroman_bytes

        return normalize_macroman_bytes
    if name == "has_macroman_signatures":
        from sarathi.shakti.font_conversion.byte_normalizer import has_macroman_signatures

        return has_macroman_signatures
    if name == "FontConversionCapability":
        from sarathi.shakti.font_conversion.capability import FontConversionCapability

        return FontConversionCapability
    if name == "FontConverter":
        from sarathi.shakti.font_conversion.converter import FontConverter

        return FontConverter
    if name == "LegacyFontDetector":
        from sarathi.shakti.font_conversion.detector import LegacyFontDetector

        return LegacyFontDetector
    if name == "TextProtector":
        from sarathi.shakti.font_conversion.protector import TextProtector

        return TextProtector
    if name == "FontConversionValidator":
        from sarathi.shakti.font_conversion.validator import FontConversionValidator

        return FontConversionValidator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
