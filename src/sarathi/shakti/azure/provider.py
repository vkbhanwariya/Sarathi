"""Provider implementation for Shakti Microsoft Azure Plugin."""

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
from sarathi.shakti.azure.client import AzureClient
from sarathi.shakti.azure.ocr import AzureOCRCapability
from sarathi.shakti.azure.plugin import (
    AZURE_OCR_DECLARATION,
    AZURE_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.azure.translation import AzureTranslationCapability


def _build_client(services: PluginServices | None) -> AzureClient:
    api_key = None
    endpoint = None
    trans_key = None
    trans_region = None
    trans_endpoint = "https://api.cognitive.microsofttranslator.com"
    timeout_sec = 60.0

    if services is not None and getattr(services, "settings", None) is not None:
        sec = services.settings.get_section("azure")
        if sec:
            api_key = sec.get("api_key")
            endpoint = sec.get("endpoint")
            trans_key = sec.get("translator_key")
            trans_region = sec.get("translator_region")
            trans_endpoint = sec.get("translator_endpoint", trans_endpoint)
            timeout_sec = float(sec.get("timeout_seconds", timeout_sec))

    return AzureClient(
        api_key=api_key,
        endpoint=endpoint,
        translator_key=trans_key,
        translator_region=trans_region,
        translator_endpoint=trans_endpoint,
        timeout_seconds=timeout_sec,
    )


class AzureProvider(PluginProvider):
    """Canonical provider for Shakti Microsoft Azure Cloud capabilities."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (AZURE_OCR_DECLARATION, AZURE_TRANSLATION_DECLARATION)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        client = _build_client(services)
        return {
            "azure_ocr": AzureOCRCapability(client=client, darpana=services.darpana),
            "azure_translation": AzureTranslationCapability(client=client),
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
            return {"azure_ocr": unavail, "azure_translation": unavail}

        client = _build_client(services)
        if client.is_configured:
            ocr_ready = CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Azure Document Intelligence credentials configured.",
            )
        else:
            ocr_ready = CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="AZURE_API_KEY or AZURE_ENDPOINT environment variable is not configured.",
            )

        trans_key = client._translator_key
        if trans_key and trans_key.strip():
            trans_ready = CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Azure Translator credentials configured.",
            )
        else:
            trans_ready = CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="AZURE_TRANSLATOR_KEY is not configured.",
            )

        return {
            "azure_ocr": ocr_ready,
            "azure_translation": trans_ready,
        }
