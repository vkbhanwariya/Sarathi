"""Plugin declaration for Shakti Translation."""

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
    plugin_id="shakti.translation",
    name="Shakti Translation",
    version="1.0.0",
    description="Local bilingual translation between Hindi and English with factual span protection.",
    capabilities=("translation",),
    metadata=MappingProxyType({"category": "shakti", "family": "translation"}),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="translation",
    plugin_id=PLUGIN_INFO.plugin_id,
    version="1.0.0",
    description="Bilingual Hindi-English translation preserving protected facts and domain terminology.",
    supported_profiles=(
        ExecutionProfile.INSTANT,
        ExecutionProfile.ACCURATE,
        ExecutionProfile.LAYOUT_PRESERVING,
        ExecutionProfile.CUSTOM,
    ),
    device_requirement=DeviceRequirement(
        preferred_devices=(DeviceType.CPU,),
        supported_devices=(DeviceType.CPU, DeviceType.GPU, DeviceType.NPU),
        parallelizable=True,
    ),
    produces_artifacts=True,
    metadata=MappingProxyType({"category": "shakti", "family": "translation"}),
)
