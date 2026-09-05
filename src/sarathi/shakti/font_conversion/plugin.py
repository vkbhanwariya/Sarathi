"""Plugin declaration for Roopa Font Conversion."""

from __future__ import annotations

from types import MappingProxyType

from sarathi.sankalpa import (
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionProfile,
    PluginInfo,
)

PLUGIN_INFO = PluginInfo(
    plugin_id="shakti.font_conversion",
    name="Roopa Font Conversion",
    version="1.0.0",
    description="Deterministic legacy font to Unicode conversion preserving protected tokens and formatting.",
    capabilities=("font_conversion",),
    metadata=MappingProxyType({"category": "shakti", "family": "font_conversion"}),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="font_conversion",
    plugin_id=PLUGIN_INFO.plugin_id,
    version="1.0.0",
    display_name="Legacy Font Conversion",
    description="Converts legacy Hindi/Devanagari encodings to standard Unicode with span protection.",

    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
    prerequisites=("read_native",),
    device_requirement=DeviceRequirement(
        preferred_devices=(DeviceType.CPU,),
        supported_devices=(DeviceType.CPU,),
        parallelizable=True,
    ),
    produces_artifacts=True,
    metadata=MappingProxyType({"category": "shakti", "family": "font_conversion"}),
)
