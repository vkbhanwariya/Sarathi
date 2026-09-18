"""Google Gemini Cloud Translation Capability implementation for Sarathi."""

from __future__ import annotations

from sarathi.sankalpa import (
    CapabilityDeclaration,
    ExecutionContext,
    Request,
    Result,
)
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.plugin import GEMINI_TRANSLATION_DECLARATION
from sarathi.shakti.translation.cloud_orchestration import execute_cloud_translation


class GeminiTranslationCapability:
    """Capability implementing Google Gemini Multimodal Cloud Translation."""

    def __init__(
        self,
        client: GeminiClient | None = None,
        declaration: CapabilityDeclaration = GEMINI_TRANSLATION_DECLARATION,
    ) -> None:
        self.declaration = declaration
        self._client = client or GeminiClient()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Gemini translation on input documents or upstream results."""
        return execute_cloud_translation(
            request=request,
            context=context,
            prior_result=prior_result,
            translate_fn=self._client.chat_translate,
            provider_id="google_gemini",
            capability_id="gemini_translation",
            default_model="gemini-2.5-flash",
            declaration=self.declaration,
        )
