"""Plugin and Capability declarations for Microsoft Azure Cloud Plugin."""

from __future__ import annotations

from types import MappingProxyType

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    PluginInfo,
    SecurityDeclaration,
)

AZURE_SECURITY = SecurityDeclaration(
    pii_access=True,
    local_processing_only=False,
    network_access=True,
    external_processing=True,
    required_secrets=("AZURE_API_KEY", "AZURE_ENDPOINT"),
)

PLUGIN_INFO = PluginInfo(
    plugin_id="sarathi.shakti.azure",
    name="Microsoft Azure Cloud Plugin",
    version="1.0.0",
    description="Cloud OCR via Azure Document Intelligence and Translation via Azure AI Translator.",
    security=AZURE_SECURITY,
    capabilities=("azure_ocr", "azure_translation"),
    metadata=MappingProxyType(
        {
            "provider": "microsoft",
            "tier": "cloud",
            "documentation": "https://learn.microsoft.com/en-us/azure/ai-services/",
        }
    ),
)

AZURE_OCR_DECLARATION = CapabilityDeclaration(
    capability_id="azure_ocr",
    plugin_id="sarathi.shakti.azure",
    version="1.0.0",
    display_name="Azure Document Intelligence OCR",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
)

AZURE_TRANSLATION_DECLARATION = CapabilityDeclaration(
    capability_id="azure_translation",
    plugin_id="sarathi.shakti.azure",
    version="1.0.0",
    display_name="Azure AI Translation",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.CUSTOM,
    ),
)
