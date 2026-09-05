"""Shakti Translation Package for Sarathi V2."""

from __future__ import annotations

from typing import Any

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


def __getattr__(name: str) -> Any:
    if name == "TranslationCapability":
        from sarathi.shakti.translation.capability import TranslationCapability

        return TranslationCapability
    if name == "CTranslate2TranslationEngine":
        from sarathi.shakti.translation.engine import CTranslate2TranslationEngine

        return CTranslate2TranslationEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
