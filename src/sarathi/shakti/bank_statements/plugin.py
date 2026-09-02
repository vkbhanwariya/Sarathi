"""Bank Statement Consolidation Plugin Declaration for Sarathi V2."""

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
    plugin_id="shakti.bank_statements",
    name="Bank Statement Consolidation",
    version="2.0.0",
    description="Deterministic Decimal-based bank statement extraction, validation, and consolidation.",
    capabilities=("bank_statements",),
    security=SecurityDeclaration(
        pii_access=True,
        local_processing_only=True,
        network_access=False,
    ),
)

CAPABILITY_DECLARATION = CapabilityDeclaration(
    capability_id="bank_statements",
    plugin_id="shakti.bank_statements",
    version="2.0.0",
    description="Extracts, validates, and consolidates bank account statements into Parquet and XLSX.",
    supported_profiles=(ExecutionProfile.INSTANT, ExecutionProfile.ACCURATE),
    prerequisites=("read_native",),
    device_requirement=DeviceRequirement(
        preferred_devices=(DeviceType.CPU,),
        supported_devices=(DeviceType.CPU,),
    ),
    produces_artifacts=True,
)
