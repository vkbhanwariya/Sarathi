"""Mistral Cloud Translation Capability implementation for Sarathi."""

from __future__ import annotations

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionContext,
    Request,
    Result,
)
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.plugin import MISTRAL_TRANSLATION_DECLARATION
from sarathi.shakti.translation.cloud_orchestration import execute_cloud_translation


class MistralTranslationCapability:
    """Capability implementing Mistral Cloud Translation (mistral-medium-latest)."""

    def __init__(
        self,
        client: MistralClient | None = None,
        declaration: CapabilityDeclaration = MISTRAL_TRANSLATION_DECLARATION,
        default_model: str = "mistral-medium-latest",
    ) -> None:
        self.declaration = declaration
        self._client = client or MistralClient()
        self.default_model = default_model

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Mistral Chat Translation on input or prior canonical document."""
        return execute_cloud_translation(
            request=request,
            context=context,
            prior_result=prior_result,
            translate_fn=self._client.chat_translate,
            provider_id="mistral",
            capability_id="mistral_translation",
            default_model=self.default_model,
            declaration=self.declaration,
            batch_translate_fn=getattr(self._client, "batch_translate", None),
        )
