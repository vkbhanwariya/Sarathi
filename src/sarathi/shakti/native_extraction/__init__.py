"""Shruti — Read / Native Extraction Capability for Sarathi V2.

Exposes:
- NativeExtractionCapability: Executable capability for byte-first native document extraction.
- CAPABILITY_DECLARATION: Declaration metadata for registration in Kosh.
- PLUGIN_INFO: Plugin registration info.
"""

from __future__ import annotations

from sarathi.shakti.native_extraction.capability import NativeExtractionCapability
from sarathi.shakti.native_extraction.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "CAPABILITY_DECLARATION",
    "NativeExtractionCapability",
    "PLUGIN_INFO",
]
