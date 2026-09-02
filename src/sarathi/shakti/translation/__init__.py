"""Shakti Translation Package for Sarathi V2."""

from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.models import (
    Language,
    TranslationDirection,
    TranslationResult,
)
from sarathi.shakti.translation.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)

PLUGIN_DECLARATION = PLUGIN_INFO

__all__ = [
    "CAPABILITY_DECLARATION",
    "Language",
    "PLUGIN_DECLARATION",
    "PLUGIN_INFO",
    "TranslationCapability",
    "TranslationDirection",
    "TranslationResult",
]
