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

        return {
            "translation": TranslationCapability(
                darpana=services.darpana,
                yantra=services.yantra,
                data_root=services.data_root,
            )
        }

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        base_data = (services.data_root if services and services.data_root else get_canonical_data_root()) / "translation"
        try:
            trans_installed = importlib.util.find_spec("ctranslate2") is not None
            trans_models = base_data / "models"
            hi_en_model = trans_models / "hi-en"
            en_hi_model = trans_models / "en-hi"

            def _is_complete_model(p: Path) -> bool:
                return (
                    p.is_dir()
                    and (p / "model.bin").is_file()
                    and (p / "spm.model").is_file()
                    and (p / "shared_vocabulary.json").is_file()
                )

            models_ready = trans_models.is_dir() and _is_complete_model(hi_en_model) and _is_complete_model(en_hi_model)
            if trans_installed and models_ready:
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
            if not models_ready:
                missing_parts.append("model assets")
            return {
                "translation": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                    reason=f"Unavailable (Missing: {', '.join(missing_parts)})",
                )
            }
        except Exception:
            return {
                "translation": CapabilityReadiness(
                    ready=False,
                    status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                    reason="Unavailable (Failed to check translation dependencies)",
                )
            }
