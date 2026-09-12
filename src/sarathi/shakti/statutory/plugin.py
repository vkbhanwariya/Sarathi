"""Statutory and Legal Document Intelligence Plugin Declaration for Sarathi."""

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
    plugin_id="shakti.statutory",
    name="Statutory & Legal Intelligence",
    version="2.0.0",
    description="Statutory and legal document metadata extraction (GST, Income Tax, MCA, eCourts).",
    capabilities=("statutory",),
    security=SecurityDeclaration(
        pii_access=True,
        local_processing_only=True,
        network_access=False,
    ),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="statutory",
    plugin_id="shakti.statutory",
    version="2.0.0",
    display_name="Statutory & Legal Extraction",
    description="Extracts and validates GSTIN, PAN, CIN, and CNR metadata from government and legal documents.",
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
)
