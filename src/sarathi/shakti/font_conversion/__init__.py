"""Roopa Font Conversion Capability Package for Sarathi V2."""

from __future__ import annotations

from typing import Any

from sarathi.shakti.font_conversion.models import (
    ConversionCandidate,
    ConversionDecision,
    ConversionMetrics,
    ConversionPlan,
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
    "FontConversionResult",
    "FontEvidence",
    "LegacyFontProfile",
    "LogicalRun",
    "ProtectedSpan",
    "CAPABILITY_DECLARATION",
    "PLUGIN_INFO",
    "TextProtector",
    "FontConversionValidator",
]


def __getattr__(name: str) -> Any:
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
