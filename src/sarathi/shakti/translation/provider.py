"""Provider implementation for Shakti Machine Translation."""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from pathlib import Path

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

        trans_data_root = (
            services.data_root
            if services.data_root and services.data_root.name == "translation"
            else (
                (services.data_root / "translation")
                if services.data_root
                else get_canonical_data_root() / "translation"
            )
        )

        return {
            "translation": TranslationCapability(
                darpana=services.darpana,
                yantra=services.yantra,
                data_root=trans_data_root,
            )
        }

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        base_data = (
            services.data_root
            if services and services.data_root and services.data_root.name == "translation"
            else (
                (services.data_root / "translation")
                if services and services.data_root
                else get_canonical_data_root() / "translation"
            )
        )
        try:
            ctranslate2_spec = importlib.util.find_spec("ctranslate2")
            sentencepiece_spec = importlib.util.find_spec("sentencepiece")
            manifest_file = base_data / "manifest.json"
            manifest_exists = manifest_file.is_file()

            trans_models = base_data / "models"

            def _is_complete_model(p: Path) -> bool:
                has_vocab = (p / "shared_vocabulary.json").is_file() or (
                    (p / "source_vocabulary.json").is_file() and (p / "target_vocabulary.json").is_file()
                )
                has_spm = (
                    (p / "spm.model").is_file()
                    or ((p / "model.SRC").is_file() and (p / "model.TGT").is_file())
                    or ((p / "src_spm.model").is_file() and (p / "tgt_spm.model").is_file())
                )
                return p.is_dir() and (p / "model.bin").is_file() and has_spm and has_vocab

            opus_hi_en = trans_models / "opus_mt" / "hi-en"
            opus_en_hi = trans_models / "opus_mt" / "en-hi"
            indic_hi_en = trans_models / "indictrans2" / "hi-en"
            indic_en_hi = trans_models / "indictrans2" / "en-hi"

            has_opus_models = _is_complete_model(opus_hi_en) and _is_complete_model(opus_en_hi)
            has_indic_models = _is_complete_model(indic_hi_en) and _is_complete_model(indic_en_hi)

            models_ready = trans_models.is_dir() and (has_indic_models or has_opus_models)
            trans_installed = ctranslate2_spec is not None and sentencepiece_spec is not None

            if trans_installed and manifest_exists and models_ready:
                if has_indic_models and has_opus_models:
                    reason_str = "Ready (IndicTrans2 CTranslate2 / OPUS-MT)"
                elif has_indic_models:
                    reason_str = "Ready (IndicTrans2 CTranslate2)"
                else:
                    reason_str = "Ready (OPUS-MT CTranslate2)"

                return {
                    "translation": CapabilityReadiness(
                        ready=True,
                        status=ReadinessStatus.READY,
                        reason=reason_str,
                    )
                }

            missing_parts = []
            if ctranslate2_spec is None:
                missing_parts.append("ctranslate2")
            if sentencepiece_spec is None:
                missing_parts.append("sentencepiece")
            if not manifest_exists:
                missing_parts.append("manifest.json")
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
