"""Plugin information and capability declaration for Shruti Native Extraction."""

from __future__ import annotations

from sarathi.sankalpa import (
    CapabilityDeclaration,
    DeviceRequirement,
    DeviceType,
    ExecutionProfile,
    PluginInfo,
    SecurityDeclaration,
)

PLUGIN_INFO = PluginInfo(
    plugin_id="shakti.native_extraction",
    name="Shruti — Native Extraction",
    version="1.0.0",
    security=SecurityDeclaration(),
    capabilities=("read_native",),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="read_native",
    plugin_id="shakti.native_extraction",
    version="1.0.0",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
    device_requirement=DeviceRequirement(
        preferred_devices=(DeviceType.CPU,),
        supported_devices=(DeviceType.CPU,),
    ),
)
