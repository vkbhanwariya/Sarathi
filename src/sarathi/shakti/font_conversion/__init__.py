"""Roopa Font Conversion Capability Package for Sarathi V2."""

from __future__ import annotations

from sarathi.shakti.font_conversion.capability import FontConversionCapability
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
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
from sarathi.shakti.font_conversion.protector import TextProtector
from sarathi.shakti.font_conversion.validator import FontConversionValidator

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
