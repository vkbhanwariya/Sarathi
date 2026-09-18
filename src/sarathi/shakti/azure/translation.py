"""Microsoft Azure Cloud Translation Capability implementation for Sarathi."""

from __future__ import annotations

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionContext,
    Request,
    Result,
)
from sarathi.shakti.azure.client import AzureClient
from sarathi.shakti.azure.plugin import AZURE_TRANSLATION_DECLARATION
from sarathi.shakti.translation.cloud_orchestration import execute_cloud_translation


class AzureTranslationCapability:
    """Capability implementing Azure AI Translator."""

    def __init__(
        self,
        client: AzureClient | None = None,
        declaration: CapabilityDeclaration = AZURE_TRANSLATION_DECLARATION,
    ) -> None:
        self.declaration = declaration
        self._client = client or AzureClient()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Azure translation on input documents or upstream results."""
        return execute_cloud_translation(
            request=request,
            context=context,
            prior_result=prior_result,
            translate_fn=lambda text, source_lang, target_lang, model, **kwargs: self._client.translate_text(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
            ),
            provider_id="azure",
            capability_id="azure_translation",
            default_model="azure-translator-v3",
            declaration=self.declaration,
        )
