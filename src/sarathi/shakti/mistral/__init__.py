"""Shakti Mistral AI Plugin Package.

Provides cloud-based OCR (mistral-ocr-latest) capability with Kavacha
security gating and zero token leaks.
"""

from __future__ import annotations

from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.ocr import MistralOCRCapability
from sarathi.shakti.mistral.plugin import (
    MISTRAL_OCR_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.mistral.provider import MistralProvider

__all__ = [
    "MISTRAL_OCR_DECLARATION",
    "PLUGIN_INFO",
    "MistralClient",
    "MistralOCRCapability",
    "MistralProvider",
]
