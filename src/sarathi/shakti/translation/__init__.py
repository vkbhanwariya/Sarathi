"""Shakti Translation Package for Sarathi."""

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
    "LegalContextBuilder",
    "LegalDocumentContext",
    "PLUGIN_INFO",
    "TranslationCapability",
    "TranslationDirection",
    "TranslationResult",
    "execute_cloud_translation",
]


def __getattr__(name: str) -> Any:
    if name == "TranslationCapability":
        from sarathi.shakti.translation.capability import TranslationCapability

        return TranslationCapability
    if name == "CTranslate2TranslationEngine":
        from sarathi.shakti.translation.engine import CTranslate2TranslationEngine

        return CTranslate2TranslationEngine
    if name in ("LegalContextBuilder", "LegalDocumentContext"):
        from sarathi.shakti.translation.legal_context import LegalContextBuilder, LegalDocumentContext

        return LegalContextBuilder if name == "LegalContextBuilder" else LegalDocumentContext
    if name == "execute_cloud_translation":
        from sarathi.shakti.translation.cloud_orchestration import execute_cloud_translation

        return execute_cloud_translation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
