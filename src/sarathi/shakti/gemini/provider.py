"""Provider implementation for Shakti Google Gemini Plugin."""

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
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.ocr import GeminiOCRCapability
from sarathi.shakti.gemini.plugin import (
    GEMINI_OCR_DECLARATION,
    GEMINI_TRANSLATION_DECLARATION,
    PLUGIN_INFO,
)
from sarathi.shakti.gemini.translation import GeminiTranslationCapability


def _build_client(services: PluginServices | None) -> GeminiClient:
    api_key = None
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    timeout_sec = 60.0
    if services is not None and getattr(services, "settings", None) is not None:
        sec = services.settings.get_section("gemini")
        if sec:
            api_key = sec.get("api_key")
            base_url = sec.get("base_url", base_url)
            timeout_sec = float(sec.get("timeout_seconds", timeout_sec))
    return GeminiClient(api_key=api_key, base_url=base_url, timeout_seconds=timeout_sec)


class GeminiProvider(PluginProvider):
    """Canonical provider for Shakti Google Gemini Cloud capabilities."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (GEMINI_OCR_DECLARATION, GEMINI_TRANSLATION_DECLARATION)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        client = _build_client(services)
        return {
            "gemini_ocr": GeminiOCRCapability(client=client, darpana=services.darpana),
            "gemini_translation": GeminiTranslationCapability(client=client),
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
            return {"gemini_ocr": unavail, "gemini_translation": unavail}

        client = _build_client(services)
        if client.is_configured:
            ready_res = CapabilityReadiness(
                ready=True,
                status=ReadinessStatus.READY,
                reason="Google Gemini API key configured and cloud client ready.",
            )
        else:
            ready_res = CapabilityReadiness(
                ready=False,
                status=ReadinessStatus.DEPENDENCY_UNAVAILABLE,
                reason="Google Gemini API key is missing. Set GEMINI_API_KEY environment variable.",
            )
        return {
            "gemini_ocr": ready_res,
            "gemini_translation": ready_res,
        }
