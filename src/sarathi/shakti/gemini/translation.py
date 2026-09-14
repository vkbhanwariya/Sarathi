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
    ProvenanceRecord,
    Request,
    Result,
)
from sarathi.sankalpa.document import transform_canonical_document
from sarathi.shakti.artifact_naming import format_artifact_filename, resolve_source_input
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.plugin import GEMINI_TRANSLATION_DECLARATION
from sarathi.shakti.text.direction import normalize_translation_direction

_BINARY_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".xls", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"})


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

        model = "gemini-2.5-flash"
        if request.custom_options and "model" in request.custom_options:
            model = str(request.custom_options["model"])

        raw_dir = request.metadata.get("direction") if request.metadata else None
        norm_dir = normalize_translation_direction(raw_dir)
        source_lang, target_lang = norm_dir.source_name, norm_dir.target_name

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

        for doc_id, doc_or_str in docs_to_translate:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            metadata_updates = {
                "model": model,
                "direction": f"{source_lang}->{target_lang}",
                "provider": "google_gemini",
            }

            if isinstance(doc_or_str, CanonicalDocument):
                trans_doc = transform_canonical_document(
                    doc_or_str,
                    text_transform_fn=_call_translate,
                    detected_type=doc_or_str.detected_type or "gemini_translated",
                    target_lang=norm_dir.target_code,
                )
                meta = dict(trans_doc.metadata) if trans_doc.metadata else {}
                meta.update(metadata_updates)
                trans_doc = replace(
                    trans_doc,
                    document_id=f"{doc_id}-translated",
                    metadata=meta,
                )
            else:
                orig_text = str(doc_or_str)
                translated_text = _call_translate(orig_text)
                trans_doc = CanonicalDocument(
                    document_id=f"{doc_id}-translated",
                    text=translated_text,
                    metadata=metadata_updates,
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
                    content=trans_doc.text.encode("utf-8"),
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
