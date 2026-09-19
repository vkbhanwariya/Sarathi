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
        default_model: str = "azure-translator-v3",
    ) -> None:
        self.declaration = declaration
        self._client = client or AzureClient()
        self.default_model = default_model

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
            default_model=self.default_model,
            declaration=self.declaration,
            batch_translate_fn=(
                (
                    lambda texts, source_lang, target_lang, model, **kwargs: self._client.translate_batch(
                        texts=texts,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                )
                if hasattr(self._client, "translate_batch")
                else None
            ),
        )
