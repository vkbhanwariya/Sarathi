"""Plugin information and capability declaration for Darshana Intake Identification."""

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
    plugin_id="shakti.darshana",
    name="Darshana — Intake Identification",
    version="1.0.0",
    security=SecurityDeclaration(),
    capabilities=("identify",),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="identify",
    plugin_id="shakti.darshana",
    version="1.0.0",
    display_name="Document Identification",
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
