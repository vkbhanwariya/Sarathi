"""Canonical Built-in Plugin Provider Catalog for Sarathi V2.

Provides one single canonical catalog of built-in Shakti plugin providers.
Consumed by Dvara for metadata registration into Kosh and by Agni for
dependency-injected capability factory construction and readiness audits.
"""

from __future__ import annotations

from sarathi.sankalpa import PluginProvider
from sarathi.shakti.bank_statements.provider import BankStatementsProvider
from sarathi.shakti.darshana.provider import DarshanaProvider
from sarathi.shakti.font_conversion.provider import FontConversionProvider
from sarathi.shakti.native_extraction.provider import NativeExtractionProvider
from sarathi.shakti.ocr.provider import OCRProvider
from sarathi.shakti.translation.provider import TranslationProvider

BUILTIN_PLUGIN_PROVIDERS: tuple[PluginProvider, ...] = (
    DarshanaProvider(),
    NativeExtractionProvider(),
    OCRProvider(),
    BankStatementsProvider(),
    FontConversionProvider(),
    TranslationProvider(),
)

__all__ = [
    "BUILTIN_PLUGIN_PROVIDERS",
    "BankStatementsProvider",
    "DarshanaProvider",
    "FontConversionProvider",
    "NativeExtractionProvider",
    "OCRProvider",
    "TranslationProvider",
]
