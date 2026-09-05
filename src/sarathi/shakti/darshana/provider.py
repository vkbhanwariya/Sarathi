"""Provider implementation for Darshana Intake Identification."""

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
from sarathi.shakti.darshana.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO


class DarshanaProvider(PluginProvider):
    """Canonical provider for Darshana intake identification."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.darshana.capability import DarshanaCapability

        return {"identify": DarshanaCapability(darpana=services.darpana)}

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        return {
            "identify": CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Ready (Intake Identification)",
            )
        }
