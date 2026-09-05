"""Provider implementation for Roopa Font Conversion."""

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
from sarathi.shakti.font_conversion.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.sutra import get_canonical_data_root


class FontConversionProvider(PluginProvider):
    """Canonical provider for Roopa Font Conversion."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.font_conversion.capability import (
            FontConversionCapability,
        )

        return {"font_conversion": FontConversionCapability(darpana=services.darpana)}

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        base_data = (services.data_root if services and services.data_root else get_canonical_data_root()) / "fonts"
        try:
            font_files = list(base_data.glob("*.json")) if base_data.exists() else []
            if font_files:
                names = [f.stem for f in font_files]
                return {
                    "font_conversion": CapabilityReadiness(
                        ready=True,
                        status=ReadinessStatus.READY,
                        reason=f"Ready ({len(names)} mapping packs: {', '.join(names)})",
                    )
                }
            return {
                "font_conversion": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.INVALID_CONFIGURATION,
                    reason="Unavailable (Missing font mapping packs)",
                )
            }
        except Exception as exc:
            return {
                "font_conversion": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.INVALID_CONFIGURATION,
                    reason=f"Unavailable (Failed to inspect font packs: {exc})",
                )
            }
