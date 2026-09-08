"""Provider implementation for Statutory & Legal Document Intelligence."""

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
from sarathi.shakti.statutory.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)


class StatutoryProvider(PluginProvider):
    """Canonical provider for Statutory & Legal Document Intelligence."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.statutory.capability import StatutoryCapability

        return {"statutory": StatutoryCapability(darpana=services.darpana)}

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        return {
            "statutory": CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Ready (Built-in checksum and heuristic extraction engine)",
            )
        }
