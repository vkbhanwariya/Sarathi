"""Provider implementation for Shakti OCR."""

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
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO
from sarathi.sutra import get_canonical_data_root


class OCRProvider(PluginProvider):
    """Canonical provider for Shakti Optical Character Recognition."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.ocr.capability import OCRCapability

        return {
            "ocr": OCRCapability(
                yantra=services.yantra,
                darpana=services.darpana,
            )
        }

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        base_data = (services.data_root if services and services.data_root else get_canonical_data_root()) / "ocr"
        try:
            from sarathi.shakti.ocr.engine import check_ocr_readiness

            ready, msg = check_ocr_readiness(data_root=base_data)
            return {
                "ocr": CapabilityReadiness(
                    ready=ready,
                    status=ReadinessStatus.READY if ready else ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                    reason=msg,
                )
            }
        except Exception as exc:
            return {
                "ocr": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                    reason=f"Unavailable (Missing OCR extra dependencies or models: {exc})",
                )
            }
