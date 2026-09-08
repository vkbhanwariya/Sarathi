"""Mistral Cloud Translation Capability implementation for Sarathi V2.

Consumes CanonicalDocument or raw input text, invokes mistral-large-latest via MistralClient,
and maps translated text into CanonicalDocument and TXT/DOCX artifacts.
"""

from __future__ import annotations

from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    CapabilityDeclaration,
    ExecutionContext,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
)
from sarathi.shakti.artifact_naming import format_artifact_filename
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.plugin import MISTRAL_TRANSLATION_DECLARATION

_DIRECTION_MAP = {
    "hi-en": ("Hindi", "English"),
    "en-hi": ("English", "Hindi"),
    "hi_to_en": ("Hindi", "English"),
    "en_to_hi": ("English", "Hindi"),
}


class MistralTranslationCapability:
    """Capability implementing Mistral Cloud Translation (mistral-large-latest)."""

    def __init__(
        self,
        client: MistralClient | None = None,
        declaration: CapabilityDeclaration = MISTRAL_TRANSLATION_DECLARATION,
    ) -> None:
        self.declaration = declaration
        self._client = client or MistralClient()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Mistral Chat Translation on input or prior canonical document."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        model = (
            request.custom_options.get("model", "mistral-large-latest")
            if request.custom_options
            else "mistral-large-latest"
        )

        # Resolve translation direction
        raw_direction = (
            request.metadata.get("direction")
            or (request.custom_options.get("direction") if request.custom_options else None)
            or "hi-en"
        )
        dir_key = str(raw_direction).lower().strip()
        source_lang, target_lang = _DIRECTION_MAP.get(dir_key, ("Hindi", "English"))

        # Resolve documents from prior_result or input file
        docs_to_process: list[tuple[str, str, tuple[PageData, ...]]] = []
        if prior_result is not None and prior_result.data is not None:
            if isinstance(prior_result.data, CanonicalDocument):
                docs_to_process.append((
                    prior_result.data.document_id,
                    prior_result.data.text,
                    prior_result.data.pages,
                ))
            elif isinstance(prior_result.data, (list, tuple)):
                for doc in prior_result.data:
                    if isinstance(doc, CanonicalDocument):
                        docs_to_process.append((doc.document_id, doc.text, doc.pages))
        else:
            for inp in request.inputs:
                try:
                    text_content = inp.source_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message=f"Failed to read input text: {inp.display_name}",
                    ) from exc
                docs_to_process.append((f"doc-{inp.input_id}", text_content, ()))

        if not docs_to_process:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No document content available for translation.",
            )

        translated_docs: list[CanonicalDocument] = []
        all_payloads: list[ArtifactPayload] = []

        for doc_id, text, pages in docs_to_process:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            translated_text = self._client.chat_translate(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                model=model,
            )

            # Map pages if available
            new_pages: list[PageData] = []
            if pages:
                for p in pages:
                    if p.text and p.text.strip():
                        p_trans = self._client.chat_translate(
                            text=p.text,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            model=model,
                        )
                    else:
                        p_trans = ""
                    new_pages.append(PageData(page_number=p.page_number, text=p_trans, spans=p.spans, tables=p.tables))

            trans_doc = CanonicalDocument(
                document_id=f"{doc_id}-translated",
                text=translated_text,
                pages=tuple(new_pages) if new_pages else (),
                metadata={
                    "model": model,
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "mistral",
                },
            )
            translated_docs.append(trans_doc)

            matching_inp = next(
                (inp for inp in request.inputs if inp.input_id in doc_id),
                request.inputs[0] if request.inputs else InputRef(input_id=doc_id, source_path=Path(f"{doc_id}.txt"), display_name=f"{doc_id}.txt", size_bytes=0),
            )
            txt_name = format_artifact_filename(matching_inp, "mistral_translated", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(matching_inp, "mistral_translated", "docx", all_inputs=request.inputs)
            stem = Path(matching_inp.display_name or doc_id).stem

            all_payloads.append(
                ArtifactPayload(
                    intent=ArtifactIntent(name=txt_name, role="translated_text", media_type="text/plain"),
                    content=translated_text.encode("utf-8"),
                )
            )
            all_payloads.append(
                build_docx_payload(
                    doc=trans_doc,
                    filename=docx_name,
                    role="translated_document",
                    header_text=f"Translation - {stem}",
                )
            )

        output_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)

        provenance = (
            ProvenanceRecord(
                capability_id="mistral_translation",
                evidence={
                    "model": model,
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "mistral",
                },
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
        )
