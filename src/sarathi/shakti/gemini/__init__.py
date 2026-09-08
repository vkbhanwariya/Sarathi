"""Google Gemini Cloud Plugin for Sarathi V2.

Exposes Gemini multimodal cloud OCR and Translation capabilities.
"""

from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.ocr import GeminiOCRCapability
from sarathi.shakti.gemini.plugin import (
    GEMINI_OCR_DECLARATION,
    GEMINI_SECURITY,
    GEMINI_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.gemini.provider import GeminiProvider
from sarathi.shakti.gemini.translation import GeminiTranslationCapability

__all__ = [
    "GEMINI_OCR_DECLARATION",
    "GEMINI_SECURITY",
    "GEMINI_TRANSLATION_DECLARATION",
    "PLUGIN_INFO",
    "GeminiClient",
    "GeminiOCRCapability",
    "GeminiProvider",
    "GeminiTranslationCapability",
]
