"""Shakti Mistral AI Plugin Package.

Provides cloud-based OCR (mistral-ocr-latest) and Translation (mistral-large-latest)
capabilities with Kavacha security gating and zero token leaks.
"""

from __future__ import annotations

from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.ocr import MistralOCRCapability
from sarathi.shakti.mistral.plugin import (
    MISTRAL_OCR_DECLARATION,
    MISTRAL_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.mistral.provider import MistralProvider
from sarathi.shakti.mistral.translation import MistralTranslationCapability

__all__ = [
    "MISTRAL_OCR_DECLARATION",
    "MISTRAL_TRANSLATION_DECLARATION",
    "PLUGIN_INFO",
    "MistralClient",
    "MistralOCRCapability",
    "MistralProvider",
    "MistralTranslationCapability",
]
