"""Provider implementation for Shakti Mistral AI Plugin."""

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
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.ocr import MistralOCRCapability
from sarathi.shakti.mistral.plugin import (
    MISTRAL_OCR_DECLARATION,
    MISTRAL_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.mistral.translation import MistralTranslationCapability


def _build_client(services: PluginServices | None) -> MistralClient:
    api_key = None
    base_url = "https://api.mistral.ai/v1"
    timeout_sec = 60.0
    if services is not None and getattr(services, "settings", None) is not None:
        sec = services.settings.get_section("mistral")
        if sec:
            api_key = sec.get("api_key")
            base_url = sec.get("base_url", base_url)
            timeout_sec = float(sec.get("timeout_seconds", timeout_sec))
    return MistralClient(api_key=api_key, base_url=base_url, timeout_seconds=timeout_sec)


class MistralProvider(PluginProvider):
    """Canonical provider for Shakti Mistral AI Cloud capabilities."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (MISTRAL_OCR_DECLARATION, MISTRAL_TRANSLATION_DECLARATION)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        client = _build_client(services)
        return {
            "mistral_ocr": MistralOCRCapability(client=client, darpana=services.darpana),
            "mistral_translation": MistralTranslationCapability(client=client),
        }

    def readiness(self, services: PluginServices | None = None) -> Mapping[str, CapabilityReadiness]:
        try:
            import httpx  # noqa: F401
        except ImportError:
            unavail = CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="HTTP transport dependency (httpx) is not installed.",
            )
            return {"mistral_ocr": unavail, "mistral_translation": unavail}

        client = _build_client(services)
        if client.is_configured:
            ready_res = CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Mistral API key configured and cloud client ready.",
            )
        else:
            ready_res = CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="MISTRAL_API_KEY environment variable is not configured.",
            )

        return {
            "mistral_ocr": ready_res,
            "mistral_translation": ready_res,
        }

