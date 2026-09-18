"""Canonical Cloud Translation Orchestration Runner for Sarathi.

Provides single, unified execution orchestration for external cloud translation providers
(Google Gemini, Mistral AI, Microsoft Azure, etc.). Eliminates duplicate boilerplate across
cloud translation adapters, enforces uniform binary validation, direction normalization,
structural placeholder protection ({{TABLE:...}}, {{PAGE:...}}), dynamic domain legal
glossary grounding, artifact generation (TXT and DOCX), and fail-closed telemetry.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

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
from sarathi.shakti.text.direction import normalize_translation_direction
from sarathi.shakti.translation.legal_context import LegalContextBuilder
from sarathi.shakti.translation.models import TranslationDirection

_BINARY_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".png",
        ".jpg",
        ".jpeg",
        ".tiff",
        ".bmp",
        ".webp",
    }
)

_STRUCTURAL_TAG_RE = re.compile(
    r"^(?:\{\{[A-Z_]+:[^}]+\}\}|<!--\s*[A-Z_]+:[^>]+-->|\[[A-Z_]+:[^\]]+\]|---\s*Page\s*\d+\s*---)$",
    re.IGNORECASE,
)
_STRUCTURAL_SPLIT_RE = re.compile(
    r"(\{\{[A-Z_]+:[^}]+\}\}|<!--\s*[A-Z_]+:[^>]+-->|\[[A-Z_]+:[^\]]+\]|---\s*Page\s*\d+\s*---)",
    re.IGNORECASE,
)


def is_structural_placeholder(text: str | None) -> bool:
    """Return True if text is an internal structural tag or page separator."""
    if not text:
        return False
    stripped = text.strip()
    return bool(_STRUCTURAL_TAG_RE.match(stripped))


def execute_cloud_translation(
    request: Request,
    context: ExecutionContext,
    prior_result: Result | None,
    translate_fn: Callable[..., str],
    provider_id: str,
    capability_id: str,
    default_model: str,
    declaration: CapabilityDeclaration,
    legal_builder: LegalContextBuilder | None = None,
) -> Result:
    """Execute canonical cloud translation pipeline with context-aware legal grounding."""
    if not isinstance(request, Request):
        raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
    if not isinstance(context, ExecutionContext):
        raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

    if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
        context.cancellation_token.check_cancelled()

    model = default_model
    if request.custom_options and "model" in request.custom_options:
        model = str(request.custom_options["model"])

    raw_dir = (
        request.metadata.get("direction")
        if request.metadata
        else (request.custom_options.get("direction") if request.custom_options else None)
    )
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
                elif isinstance(item, str):
                    docs_to_translate.append((f"input-{idx}", item))
        elif isinstance(data, str):
            docs_to_translate.append(("prior-doc", data))
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
            if not inp.source_path:
                continue
            try:
                text_content = inp.source_path.read_text(encoding="utf-8", errors="replace")
                docs_to_translate.append((inp.input_id, text_content))
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message=f"Failed to read input text file: {inp.display_name}",
                ) from exc

    if not docs_to_translate:
        raise DoshError(
            code=FailureCode.VALIDATION_FAILED,
            message="No document content available for translation.",
        )

    # Extract legal context across inputs
    combined_sample_text: list[str] = []
    for _, d_or_s in docs_to_translate:
        if isinstance(d_or_s, CanonicalDocument):
            if d_or_s.text:
                combined_sample_text.append(d_or_s.text)
            elif d_or_s.pages:
                combined_sample_text.extend(p.text for p in d_or_s.pages if p.text)
        else:
            combined_sample_text.append(str(d_or_s))

    full_sample = "\n\n".join(combined_sample_text)
    builder = legal_builder or LegalContextBuilder()
    trans_direction = (
        TranslationDirection.EN_TO_HI if norm_dir.direction_key == "en-hi" else TranslationDirection.HI_TO_EN
    )
    legal_context = builder.extract_context(
        text=full_sample,
        direction=trans_direction,
        custom_options=request.custom_options,
    )

    system_prompt: str | None = None
    if legal_context.is_legal_document:
        system_prompt = builder.format_system_prompt(
            context=legal_context,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    translated_docs: list[CanonicalDocument] = []
    all_payloads: list[ArtifactPayload] = []
    trans_memo: dict[str, str] = {}

    def _call_translate(text: str) -> str:
        if not text or not text.strip():
            return text
        if is_structural_placeholder(text):
            return text

        if "{{" in text and ("{{TABLE:" in text or "{{PAGE:" in text):
            chunks = _STRUCTURAL_SPLIT_RE.split(text)
            translated_chunks: list[str] = []
            for c in chunks:
                if is_structural_placeholder(c):
                    translated_chunks.append(c)
                elif c.strip():
                    translated_chunks.append(_call_translate(c))
                else:
                    translated_chunks.append(c)
            return "".join(translated_chunks)

        if text not in trans_memo:
            # Invoke provider-specific translate callback
            if system_prompt:
                try:
                    trans_memo[text] = translate_fn(
                        text=text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        model=model,
                        system_prompt=system_prompt,
                    )
                except TypeError:
                    trans_memo[text] = translate_fn(
                        text=text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        model=model,
                    )
            else:
                trans_memo[text] = translate_fn(
                    text=text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    model=model,
                )
        return trans_memo[text]

    for doc_id, doc_or_str in docs_to_translate:
        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        metadata_updates: dict[str, Any] = {
            "model": model,
            "direction": f"{source_lang}->{target_lang}",
            "provider": provider_id,
            "legal_context": legal_context.to_dict(),
        }

        if isinstance(doc_or_str, CanonicalDocument):
            trans_doc = transform_canonical_document(
                doc_or_str,
                text_transform_fn=_call_translate,
                detected_type=doc_or_str.detected_type or f"{provider_id}_translated",
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
        txt_name = format_artifact_filename(matching_inp, f"{provider_id}_translated", "txt", all_inputs=request.inputs)
        docx_name = format_artifact_filename(
            matching_inp, f"{provider_id}_translated", "docx", all_inputs=request.inputs
        )
        stem = Path(matching_inp.display_name or doc_id).stem if matching_inp else doc_id

        all_payloads.append(
            ArtifactPayload(
                intent=ArtifactIntent(name=txt_name, role="translated_text", media_type="text/plain"),
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
                header_text=f"{provider_id.replace('_', ' ').title()} Translation - {stem}",
            )
        all_payloads.append(docx_payload)

    output_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)

    provenance = (
        ProvenanceRecord(
            capability_id=capability_id,
            evidence={
                "model": model,
                "direction": f"{source_lang}->{target_lang}",
                "provider": provider_id,
                "legal_context": legal_context.to_dict(),
            },
        ),
    )

    return Result(
        data=output_data,
        artifact_payloads=tuple(all_payloads),
        provenance=provenance,
    )
