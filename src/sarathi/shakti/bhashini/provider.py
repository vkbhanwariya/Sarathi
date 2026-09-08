"""Provider implementation for Shakti Bhashini Plugin."""

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
from sarathi.shakti.bhashini.client import BhashiniClient
from sarathi.shakti.bhashini.ocr import BhashiniOCRCapability
from sarathi.shakti.bhashini.plugin import (
    BHASHINI_OCR_DECLARATION,
    BHASHINI_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.bhashini.translation import BhashiniTranslationCapability


def _build_client(services: PluginServices | None) -> BhashiniClient:
    user_id = None
    api_key = None
    inf_key = None
    url = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"
    timeout_sec = 60.0

    if services is not None and getattr(services, "settings", None) is not None:
        sec = services.settings.get_section("bhashini")
        if sec:
            user_id = sec.get("user_id")
            api_key = sec.get("api_key")
            inf_key = sec.get("inference_key")
            url = sec.get("pipeline_url", url)
            timeout_sec = float(sec.get("timeout_seconds", timeout_sec))

    return BhashiniClient(
        user_id=user_id,
        api_key=api_key,
        inference_key=inf_key,
        pipeline_url=url,
        timeout_seconds=timeout_sec,
    )


class BhashiniProvider(PluginProvider):
    """Canonical provider for Shakti Bhashini (NLTM / AI4Bharat) Cloud capabilities."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (BHASHINI_OCR_DECLARATION, BHASHINI_TRANSLATION_DECLARATION)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        client = _build_client(services)
        return {
            "bhashini_ocr": BhashiniOCRCapability(client=client, darpana=services.darpana),
            "bhashini_translation": BhashiniTranslationCapability(client=client),
        }

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        client = _build_client(services)
        if client.is_configured:
            ready_res = CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Bhashini credentials configured and client ready.",
            )
        else:
            ready_res = CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="BHASHINI_USER_ID, BHASHINI_API_KEY, or BHASHINI_INFERENCE_KEY is not configured.",
            )

        return {
            "bhashini_ocr": ready_res,
            "bhashini_translation": ready_res,
        }
