"""Plugin and Capability declarations for Google Gemini Cloud Plugin."""

from __future__ import annotations

from types import MappingProxyType

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    PluginInfo,
    SecurityDeclaration,
)

GEMINI_SECURITY = SecurityDeclaration(
    pii_access=True,
    local_processing_only=False,
    network_access=True,
    external_processing=True,
    required_secrets=("GEMINI_API_KEY",),
)

PLUGIN_INFO = PluginInfo(
    plugin_id="sarathi.shakti.gemini",
    name="Google Gemini Cloud Plugin",
    version="1.0.0",
    description="Cloud OCR and Translation capabilities powered by Google Gemini multimodal REST API.",
    security=GEMINI_SECURITY,
    capabilities=("gemini_ocr", "gemini_translation"),
    metadata=MappingProxyType(
        {
            "provider": "google",
            "tier": "cloud",
            "documentation": "https://ai.google.dev",
        }
    ),
)

GEMINI_OCR_DECLARATION = CapabilityDeclaration(
    capability_id="gemini_ocr",
    plugin_id="sarathi.shakti.gemini",
    version="1.0.0",
    display_name="Google Gemini Cloud OCR",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
)

GEMINI_TRANSLATION_DECLARATION = CapabilityDeclaration(
    capability_id="gemini_translation",
    plugin_id="sarathi.shakti.gemini",
    version="1.0.0",
    display_name="Google Gemini Cloud Translation",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.CUSTOM,
    ),
)
