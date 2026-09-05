"""Provider implementation for Shakti Machine Translation."""

from __future__ import annotations

import importlib.util
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
from sarathi.shakti.translation.plugin import (
    CAPABILITY_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.sutra import get_canonical_data_root


class TranslationProvider(PluginProvider):
    """Canonical provider for Shakti Machine Translation."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (CAPABILITY_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        from sarathi.shakti.translation.capability import (
            TranslationCapability,
        )

        return {"translation": TranslationCapability(darpana=services.darpana)}

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        base_data = (services.data_root if services and services.data_root else get_canonical_data_root()) / "translation"
        try:
            trans_installed = importlib.util.find_spec("ctranslate2") is not None
            trans_models = base_data / "models"
            hi_en_model = trans_models / "hi-en"
            en_hi_model = trans_models / "en-hi"
            if trans_installed and trans_models.exists() and hi_en_model.exists() and en_hi_model.exists():
                return {
                    "translation": CapabilityReadiness(
                        ready=True,
                        status=ReadinessStatus.READY,
                        reason="Ready (IndicTrans2 CTranslate2)",
                    )
                }

            missing_parts = []
            if not trans_installed:
                missing_parts.append("ctranslate2 extra")
            if not (trans_models.exists() and hi_en_model.exists() and en_hi_model.exists()):
                missing_parts.append("model assets")
            return {
                "translation": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                    reason=f"Unavailable (Missing: {', '.join(missing_parts)})",
                )
            }
        except Exception as exc:
            return {
                "translation": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                    reason=f"Unavailable (Failed to check translation dependencies: {exc})",
                )
            }
