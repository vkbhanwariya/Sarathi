"""Plugin information and capability declaration for OCR."""

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
    plugin_id="shakti.ocr",
    name="OCR",
    version="1.0.0",
    security=SecurityDeclaration(),
    capabilities=("ocr",),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="ocr",
    plugin_id="shakti.ocr",
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
