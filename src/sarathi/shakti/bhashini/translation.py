"""Bhashini IndicTrans2 Translation Capability implementation for Sarathi V2."""

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
from sarathi.shakti.bhashini.client import BhashiniClient
from sarathi.shakti.bhashini.plugin import BHASHINI_TRANSLATION_DECLARATION
from sarathi.shakti.docx_exporter import build_docx_payload


class BhashiniTranslationCapability:
    """Capability implementing Bhashini IndicTrans2 NMT."""

    def __init__(
        self,
        client: BhashiniClient | None = None,
        declaration: CapabilityDeclaration = BHASHINI_TRANSLATION_DECLARATION,
    ) -> None:
        self.declaration = declaration
        self._client = client or BhashiniClient()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Bhashini translation on input documents or upstream results."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        direction = "hi-en"
        if request.metadata and "direction" in request.metadata:
            direction = str(request.metadata["direction"]).lower()

        if direction in ("hi-en", "hi_to_en"):
            source_lang, target_lang = "hi", "en"
        elif direction in ("en-hi", "en_to_hi"):
            source_lang, target_lang = "en", "hi"
        else:
            parts = direction.split("-")
            source_lang = parts[0] if len(parts) > 0 else "hi"
            target_lang = parts[1] if len(parts) > 1 else "en"

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

        for doc_id, doc_or_str in docs_to_translate:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            orig_text = doc_or_str.text if isinstance(doc_or_str, CanonicalDocument) else str(doc_or_str)

            translated_text = self._client.translate_text(
                text=orig_text,
                source_lang=source_lang,
                target_lang=target_lang,
            )

            new_pages: list[PageData] = []
            if isinstance(doc_or_str, CanonicalDocument) and doc_or_str.pages:
                for p in doc_or_str.pages:
                    p_trans = self._client.translate_text(
                        text=p.text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                    new_pages.append(PageData(page_number=p.page_number, text=p_trans, spans=p.spans, tables=p.tables))

            trans_doc = CanonicalDocument(
                document_id=f"{doc_id}-translated",
                text=translated_text,
                pages=tuple(new_pages) if new_pages else (),
                metadata={
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "bhashini_indictrans2",
                },
            )
            translated_docs.append(trans_doc)

            matching_inp = next(
                (inp for inp in request.inputs if inp.input_id in doc_id),
                request.inputs[0] if request.inputs else InputRef(input_id=doc_id, source_path=Path(f"{doc_id}.txt"), display_name=f"{doc_id}.txt", size_bytes=0),
            )
            txt_name = format_artifact_filename(matching_inp, "bhashini_translated", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(matching_inp, "bhashini_translated", "docx", all_inputs=request.inputs)
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
                    header_text=f"Bhashini Translation - {stem}",
                )
            )

        output_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)

        provenance = (
            ProvenanceRecord(
                capability_id="bhashini_translation",
                evidence={
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": "bhashini_indictrans2",
                },
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
        )
