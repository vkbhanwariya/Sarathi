"""Bhashini Cloud Plugin for Sarathi.

Exposes Bhashini Chitrakshar OCR and IndicTrans2 Translation capabilities.
"""

from sarathi.shakti.bhashini.client import BhashiniClient
from sarathi.shakti.bhashini.ocr import BhashiniOCRCapability
from sarathi.shakti.bhashini.plugin import (
    BHASHINI_OCR_DECLARATION,
    BHASHINI_SECURITY,
    BHASHINI_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.bhashini.provider import BhashiniProvider
from sarathi.shakti.bhashini.translation import BhashiniTranslationCapability

__all__ = [
    "BHASHINI_OCR_DECLARATION",
    "BHASHINI_SECURITY",
    "BHASHINI_TRANSLATION_DECLARATION",
    "PLUGIN_INFO",
    "BhashiniClient",
    "BhashiniOCRCapability",
    "BhashiniProvider",
    "BhashiniTranslationCapability",
]
