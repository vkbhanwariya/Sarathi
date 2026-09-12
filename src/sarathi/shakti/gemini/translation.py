"""Google Gemini Cloud Translation Capability implementation for Sarathi."""

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
    PageData,
    ProvenanceRecord,
    Request,
    Result,
)
from sarathi.shakti.artifact_naming import format_artifact_filename, resolve_source_input
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.plugin import GEMINI_TRANSLATION_DECLARATION

_DIRECTION_MAP = {
    "hi-en": ("Hindi", "English"),
    "hi_to_en": ("Hindi", "English"),
    "en-hi": ("English", "Hindi"),
    "en_to_hi": ("English", "Hindi"),
    "auto-en": ("the source language", "English"),
    "auto-hi": ("the source language", "Hindi"),
}


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
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        model = (
            request.custom_options.get("model", "gemini-2.5-flash")
            if request.custom_options
            else "gemini-2.5-flash"
        )

        direction = "hi-en"
        if request.metadata and "direction" in request.metadata:
            direction = str(request.metadata["direction"]).lower()

        source_lang, target_lang = _DIRECTION_MAP.get(direction, ("Hindi", "English"))

        docs_to_translate: list[tuple[str, CanonicalDocument | str]] = []
        if prior_result is not None and prior_result.data is not None:
            data = prior_result.data
            if isinstance(data, CanonicalDocument):
                docs_to_translate.append((data.document_id, data))
            elif isinstance(data, (list, tuple)):
                for idx, item in enumerate(data):
                    if isinstance(item, CanonicalDocument):
                        docs_to_translate.append((item.document_id, item))
                    else:
                        docs_to_translate.append((f"input-{idx}", str(item)))
            else:
                docs_to_translate.append(("prior-doc", str(data)))
        else:
            for inp in request.inputs:
                try:
                    text_content = inp.source_path.read_text(encoding="utf-8", errors="replace")
                    docs_to_translate.append((inp.input_id, text_content))
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message=f"Failed to read input text file: {inp.display_name}",
                    ) from exc

        translated_docs: list[CanonicalDocument] = []
        all_payloads: list[ArtifactPayload] = []
        trans_memo: dict[tuple[str, str, str, str], str] = {}

        def _call_translate(text: str) -> str:
            memo_key = (text, source_lang, target_lang, model)
            if memo_key not in trans_memo:
                trans_memo[memo_key] = self._client.chat_translate(
                    text=text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    model=model,
                )
            return trans_memo[memo_key]

        for doc_id, doc_or_str in docs_to_translate:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            orig_text = doc_or_str.text if isinstance(doc_or_str, CanonicalDocument) else str(doc_or_str)
            translated_text = _call_translate(orig_text)

            new_pages: list[PageData] = []
            if isinstance(doc_or_str, CanonicalDocument) and doc_or_str.pages:
                for p in doc_or_str.pages:
                    p_trans = _call_translate(p.text)
                    new_pages.append(replace(p, text=p_trans))

            metadata = dict(doc_or_str.metadata) if isinstance(doc_or_str, CanonicalDocument) else {}
            metadata.update(
                {
                    "model": model,
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "google_gemini",
                }
            )
            trans_doc = (
                replace(
                    doc_or_str,
                    document_id=f"{doc_id}-translated",
                    text=translated_text,
                    pages=tuple(new_pages),
                    metadata=metadata,
                )
                if isinstance(doc_or_str, CanonicalDocument)
                else CanonicalDocument(
                    document_id=f"{doc_id}-translated",
                    text=translated_text,
                    metadata=metadata,
                )
            )
            translated_docs.append(trans_doc)

            matching_inp = resolve_source_input(
                request.inputs,
                source_input_id=doc_or_str.source_input_id if isinstance(doc_or_str, CanonicalDocument) else None,
                document_id=doc_id,
            )
            txt_name = format_artifact_filename(matching_inp, "gemini_translated", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(matching_inp, "gemini_translated", "docx", all_inputs=request.inputs)
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
                    header_text=f"Gemini Translation - {stem}",
                )
            )

        output_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)

        provenance = (
            ProvenanceRecord(
                capability_id="gemini_translation",
                evidence={
                    "model": model,
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "google_gemini",
                },
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
        )
