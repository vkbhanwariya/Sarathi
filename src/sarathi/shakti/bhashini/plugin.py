"""Plugin and Capability declarations for Bhashini (NLTM / AI4Bharat) Cloud Plugin."""

from __future__ import annotations

from types import MappingProxyType

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionProfile,
    PluginInfo,
    SecurityDeclaration,
)

BHASHINI_SECURITY = SecurityDeclaration(
    pii_access=True,
    local_processing_only=False,
    network_access=True,
    external_processing=True,
    required_secrets=("BHASHINI_USER_ID", "BHASHINI_API_KEY", "BHASHINI_INFERENCE_KEY"),
)

PLUGIN_INFO = PluginInfo(
    plugin_id="sarathi.shakti.bhashini",
    name="Bhashini Cloud Plugin",
    version="1.0.0",
    description="Govt. of India National Language Translation Mission (NLTM) OCR and IndicTrans2 Translation.",
    security=BHASHINI_SECURITY,
    capabilities=("bhashini_ocr", "bhashini_translation"),
    metadata=MappingProxyType(
        {
            "provider": "bhashini",
            "tier": "national_mission",
            "documentation": "https://bhashini.gov.in",
        }
    ),
)

BHASHINI_OCR_DECLARATION = CapabilityDeclaration(
    capability_id="bhashini_ocr",
    plugin_id="sarathi.shakti.bhashini",
    version="1.0.0",
    display_name="Bhashini Chitrakshar OCR",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
)

BHASHINI_TRANSLATION_DECLARATION = CapabilityDeclaration(
    capability_id="bhashini_translation",
    plugin_id="sarathi.shakti.bhashini",
    version="1.0.0",
    display_name="Bhashini IndicTrans2 Translation",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.CUSTOM,
    ),
)
