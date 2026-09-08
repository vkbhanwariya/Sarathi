"""Plugin metadata and capability declarations for Shakti Mistral AI."""

from __future__ import annotations

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    PluginInfo,
    SecurityDeclaration,
)

PLUGIN_INFO = PluginInfo(
    plugin_id="shakti.mistral",
    name="Mistral AI",
    version="1.0.0",
    security=SecurityDeclaration(
        pii_access=True,
        local_processing_only=False,
        network_access=True,
        external_processing=True,
        required_secrets=("MISTRAL_API_KEY",),
    ),
    capabilities=("mistral_ocr", "mistral_translation"),
)

MISTRAL_OCR_DECLARATION = CapabilityDeclaration(
    capability_id="mistral_ocr",
    plugin_id="shakti.mistral",
    version="1.0.0",
    display_name="Mistral Cloud OCR",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
)

MISTRAL_TRANSLATION_DECLARATION = CapabilityDeclaration(
    capability_id="mistral_translation",
    plugin_id="shakti.mistral",
    version="1.0.0",
    display_name="Mistral Cloud Translation",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.CUSTOM,
    ),
)
