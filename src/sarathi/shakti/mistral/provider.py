"""Provider implementation for Shakti Mistral AI Plugin."""

from __future__ import annotations

from collections.abc import Mapping

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
    PLUGIN_INFO,
)


def _build_client(services: PluginServices | None) -> MistralClient:
    api_key = None
    base_url = "https://api.mistral.ai/v1"
    timeout_sec = 60.0
    rate_limit_delay_sec = 0.5
    if services is not None and getattr(services, "settings", None) is not None:
        sec = services.settings.get_section("mistral")
        if sec:
            api_key = sec.get("api_key")
            base_url = sec.get("base_url", base_url)
            timeout_sec = float(sec.get("timeout_seconds", timeout_sec))
            rate_limit_delay_sec = float(sec.get("rate_limit_delay_seconds", rate_limit_delay_sec))
    return MistralClient(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_sec,
        rate_limit_delay_seconds=rate_limit_delay_sec,
    )


class MistralProvider(PluginProvider):
    """Canonical provider for Shakti Mistral AI Cloud capabilities."""

    @property
    def plugin_info(self) -> PluginInfo:
        return PLUGIN_INFO

    @property
    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        return (MISTRAL_OCR_DECLARATION,)

    def create_capabilities(self, services: PluginServices) -> Mapping[str, Capability]:
        client = _build_client(services)
        model_ocr = "mistral-ocr-latest"
        if services is not None and getattr(services, "settings", None) is not None:
            sec = services.settings.get_section("mistral")
            if sec:
                model_ocr = str(sec.get("model_ocr", model_ocr))
        return {
            "mistral_ocr": MistralOCRCapability(
                client=client,
                darpana=services.darpana,
                default_model=model_ocr,
            ),
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
            return {"mistral_ocr": unavail}

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
        }
