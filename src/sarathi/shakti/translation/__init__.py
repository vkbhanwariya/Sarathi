"""Shakti Translation Package for Sarathi V2."""

from sarathi.shakti.translation.capability import TranslationCapability
from sarathi.shakti.translation.engine import CTranslate2TranslationEngine
from sarathi.shakti.translation.models import (
    Language,
    TranslationDirection,
    TranslationResult,
)
from sarathi.shakti.translation.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)

__all__ = [
    "CAPABILITY_DECLARATION",
    "CTranslate2TranslationEngine",
    "Language",
    "PLUGIN_INFO",
    "TranslationCapability",
    "TranslationDirection",
    "TranslationResult",
]
