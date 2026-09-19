"""Roopa Font Conversion Capability Package for Sarathi."""

from __future__ import annotations

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
    "has_macroman_signatures",
]

from sarathi.shakti.text.lazy import lazy_exports

lazy_exports(
    globals(),
    {
        "VisualFontResolver": ".visual_resolver:VisualFontResolver",
        "VisualFontCandidate": ".visual_resolver:VisualFontCandidate",
        "VisualFontEvidence": ".visual_resolver:VisualFontEvidence",
        "BinaryFontMetadata": ".font_inspector:BinaryFontMetadata",
        "inspect_font_bytes": ".font_inspector:inspect_font_bytes",
        "compute_cmap_signature": ".font_inspector:compute_cmap_signature",
        "compute_anchor_outline_hashes": ".font_inspector:compute_anchor_outline_hashes",
        "DEFAULT_ANCHOR_SYMBOLS": ".font_inspector:DEFAULT_ANCHOR_SYMBOLS",
        "normalize_macroman_bytes": ".byte_normalizer:normalize_macroman_bytes",
        "has_macroman_signatures": ".byte_normalizer:has_macroman_signatures",
        "FontConversionCapability": ".capability:FontConversionCapability",
        "FontConverter": ".converter:FontConverter",
        "LegacyFontDetector": ".detector:LegacyFontDetector",
        "TextProtector": ".protector:TextProtector",
        "FontConversionValidator": ".validator:FontConversionValidator",
    },
)
