"""Shakti Translation Package for Sarathi."""

from __future__ import annotations

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
    "ProperNounGuard",
    "transliterate_devanagari_to_latin",
]


from sarathi.shakti.text.lazy import lazy_exports

lazy_exports(
    globals(),
    {
        "ProperNounGuard": ".proper_noun_guard:ProperNounGuard",
        "transliterate_devanagari_to_latin": ".proper_noun_guard:transliterate_devanagari_to_latin",
        "TranslationCapability": ".capability:TranslationCapability",
        "CTranslate2TranslationEngine": ".engine:CTranslate2TranslationEngine",
        "LegalContextBuilder": ".legal_context:LegalContextBuilder",
        "LegalDocumentContext": ".legal_context:LegalDocumentContext",
        "execute_cloud_translation": ".cloud_orchestration:execute_cloud_translation",
    },
)
