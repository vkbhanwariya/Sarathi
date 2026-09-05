"""Provider implementation for Shruti Native Extraction."""

from __future__ import annotations

from typing import Mapping

from sarathi.sankalpa import (
    Capability,
    CapabilityDeclaration,
    CapabilityReadiness,
    PluginInfo,
    PluginProvider,
    PluginServices,
    ReadinessStatus,
)
from sarathi.shakti.native_extraction.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)


class NativeExtractionProvider(PluginProvider):
    """Canonical provider for Shruti native document extraction."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.native_extraction.capability import (
            NativeExtractionCapability,
        )

        return {"read_native": NativeExtractionCapability(darpana=services.darpana)}

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        return {
            "read_native": CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Ready (Standard Extraction)",
            )
        }
