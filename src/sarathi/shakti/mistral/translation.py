"""Mistral Cloud Translation Capability implementation for Sarathi.

Consumes CanonicalDocument or raw input text, invokes mistral-large-latest via MistralClient,
and maps translated text into CanonicalDocument and TXT/DOCX artifacts.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    CapabilityDeclaration,
    ExecutionContext,
    ProvenanceRecord,
    Request,
    Result,
)
from sarathi.sankalpa.document import transform_canonical_document
from sarathi.shakti.artifact_naming import format_artifact_filename, resolve_source_input
from sarathi.shakti.docx_exporter import (
    build_docx_payload,
    transform_docx_translation_artifact,
)
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.plugin import MISTRAL_TRANSLATION_DECLARATION
from sarathi.shakti.text.direction import normalize_translation_direction

_BINARY_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"})


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

        raw_direction = (
            request.metadata.get("direction")
            if request.metadata
            else (request.custom_options.get("direction") if request.custom_options else None)
        )
        norm_dir = normalize_translation_direction(raw_direction)
        source_lang, target_lang = norm_dir.source_name, norm_dir.target_name

        docs_to_process: list[CanonicalDocument] = []
        if prior_result is not None and prior_result.data is not None:
            if isinstance(prior_result.data, CanonicalDocument):
                docs_to_process.append(prior_result.data)
            elif isinstance(prior_result.data, (list, tuple)):
                docs_to_process.extend(
                    doc for doc in prior_result.data if isinstance(doc, CanonicalDocument)
                )
        else:
            for inp in request.inputs:
                suffix = inp.source_path.suffix.lower() if inp.source_path else ""
                if suffix in _BINARY_EXTENSIONS:
                    raise DoshError(
                        code=FailureCode.VALIDATION_FAILED,
                        message=(
                            f"Binary document '{inp.display_name}' must be processed through an extraction stage "
                            f"(read_native/ocr) before cloud translation."
                        ),
                    )
                try:
                    text_content = inp.source_path.read_text(encoding="utf-8")
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message=f"Failed to read input text: {inp.display_name}",
                    ) from exc
                docs_to_process.append(
                    CanonicalDocument(
                        document_id=f"doc-{inp.input_id}",
                        source_input_id=inp.input_id,
                        text=text_content,
                    )
                )

        if not docs_to_process:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No document content available for translation.",
            )

        translated_docs: list[CanonicalDocument] = []
        all_payloads = []
        trans_memo: dict[tuple[str, str, str, str], str] = {}

        def _call_translate(text: str) -> str:
            if not text or not text.strip():
                return text
            memo_key = (text, source_lang, target_lang, model)
            if memo_key not in trans_memo:
                trans_memo[memo_key] = self._client.chat_translate(
                    text=text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    model=model,
                )
            return trans_memo[memo_key]

        for doc in docs_to_process:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            trans_doc = transform_canonical_document(
                doc,
                text_transform_fn=_call_translate,
                detected_type=doc.detected_type or "mistral_translated",
                target_lang=norm_dir.target_code,
            )

            metadata = dict(trans_doc.metadata) if trans_doc.metadata else {}
            metadata.update(
                {
                    "model": model,
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "mistral",
                }
            )
            trans_doc = replace(
                trans_doc,
                document_id=f"{doc.document_id}-translated",
                metadata=metadata,
            )
            translated_docs.append(trans_doc)

            matching_inp = resolve_source_input(
                request.inputs,
                source_input_id=doc.source_input_id,
                document_id=doc.document_id,
            )

            txt_name = format_artifact_filename(
                matching_inp,
                "mistral_translated",
                "txt",
                all_inputs=request.inputs,
            )
            docx_name = format_artifact_filename(
                matching_inp,
                "mistral_translated",
                "docx",
                all_inputs=request.inputs,
            )
            stem = Path(matching_inp.display_name or doc.document_id).stem

            all_payloads.append(
                ArtifactPayload(
                    intent=ArtifactIntent(
                        name=txt_name,
                        role="translated_text",
                        media_type="text/plain",
                    ),
                    content=trans_doc.text.encode("utf-8"),
                )
            )
            docx_payload = None
            if matching_inp and matching_inp.source_path and str(matching_inp.source_path).lower().endswith(".docx"):
                try:
                    docx_bytes = matching_inp.source_path.read_bytes()
                    docx_payload = transform_docx_translation_artifact(
                        docx_bytes,
                        translate_fn=lambda batch: [_call_translate(s) for s in batch],
                        filename=docx_name,
                        role="translated_document",
                    )
                except Exception:
                    docx_payload = None

            if docx_payload is None:
                docx_payload = build_docx_payload(
                    doc=trans_doc,
                    filename=docx_name,
                    role="translated_document",
                    header_text=f"Translation - {stem}",
                )
            all_payloads.append(docx_payload)

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
