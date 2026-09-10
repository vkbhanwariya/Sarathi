"""Microsoft Azure Cloud Plugin for Sarathi.

Exposes Azure Document Intelligence OCR and Azure AI Translator capabilities.
"""

from sarathi.shakti.azure.client import AzureClient
from sarathi.shakti.azure.ocr import AzureOCRCapability
from sarathi.shakti.azure.plugin import (
    AZURE_OCR_DECLARATION,
    AZURE_SECURITY,
    AZURE_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.azure.provider import AzureProvider
from sarathi.shakti.azure.translation import AzureTranslationCapability

__all__ = [
    "AZURE_OCR_DECLARATION",
    "AZURE_SECURITY",
    "AZURE_TRANSLATION_DECLARATION",
    "PLUGIN_INFO",
    "AzureClient",
    "AzureOCRCapability",
    "AzureProvider",
    "AzureTranslationCapability",
]
