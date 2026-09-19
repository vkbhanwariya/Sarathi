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
from sarathi.shakti.translation.harmonizer import GlossaryHarmonizer
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
    batch_translate_fn: Callable[..., list[str]] | None = None,
) -> Result:
    """Execute canonical cloud translation pipeline with context-aware legal grounding and batch optimization."""
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

    builder = legal_builder or LegalContextBuilder()
    trans_direction = (
        TranslationDirection.EN_TO_HI if norm_dir.direction_key == "en-hi" else TranslationDirection.HI_TO_EN
    )
    custom_vars = request.custom_options.get("custom_variants") if request.custom_options else None
    harmonizer = GlossaryHarmonizer(custom_variants=custom_vars)

    translated_docs: list[CanonicalDocument] = []
    all_payloads: list[ArtifactPayload] = []
    all_provenance: list[ProvenanceRecord] = []

    for doc_id, doc_or_str in docs_to_translate:
        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        # 1. Extract document-scoped text for isolated legal context extraction
        doc_sample_parts: list[str] = []
        if isinstance(doc_or_str, CanonicalDocument):
            if doc_or_str.text:
                doc_sample_parts.append(doc_or_str.text)
            for t in doc_or_str.tables:
                if t.headers:
                    doc_sample_parts.append(" ".join(str(c) for c in t.headers))
                for r in t.rows:
                    doc_sample_parts.append(" ".join(str(c) for c in r))
            if doc_or_str.pages:
                doc_sample_parts.extend(p.text for p in doc_or_str.pages if p.text)
        else:
            doc_sample_parts.append(str(doc_or_str))

        doc_sample = "\n\n".join(doc_sample_parts)

        # 2. Compute document-isolated legal context and system prompt
        doc_legal_context = builder.extract_context(
            text=doc_sample,
            direction=trans_direction,
            custom_options=request.custom_options,
        )
        doc_system_prompt: str | None = None
        if doc_legal_context.is_legal_document:
            doc_system_prompt = builder.format_system_prompt(
                context=doc_legal_context,
                source_lang=source_lang,
                target_lang=target_lang,
            )

        # 3. Document-scoped translation memo
        trans_memo: dict[str, str] = {}

        # 4. Pre-seed translation memo via batch translation if available
        if batch_translate_fn is not None:
            seen_texts: set[str] = set()
            texts_to_batch: list[str] = []

            def _collect_for_batch(raw_val: str | None) -> None:
                if not raw_val or not raw_val.strip():
                    return
                if is_structural_placeholder(raw_val):
                    return
                if "{{" in raw_val and ("{{TABLE:" in raw_val or "{{PAGE:" in raw_val):
                    for part in _STRUCTURAL_SPLIT_RE.split(raw_val):
                        _collect_for_batch(part)
                    return
                cleaned = raw_val.strip()
                if cleaned not in seen_texts:
                    seen_texts.add(cleaned)
                    texts_to_batch.append(cleaned)

            if isinstance(doc_or_str, CanonicalDocument):
                if not doc_or_str.pages:
                    _collect_for_batch(doc_or_str.text)
                for p in doc_or_str.pages:
                    _collect_for_batch(p.text)
                    for s in p.spans:
                        _collect_for_batch(s.text)
                    for tbl in p.tables:
                        for h in tbl.headers:
                            _collect_for_batch(str(h))
                        for r in tbl.rows:
                            for c in r:
                                _collect_for_batch(str(c))
                for tbl in doc_or_str.tables:
                    for h in tbl.headers:
                        _collect_for_batch(str(h))
                    for r in tbl.rows:
                        for c in r:
                            _collect_for_batch(str(c))
            else:
                _collect_for_batch(str(doc_or_str))

            if texts_to_batch:
                try:
                    batched_outputs = batch_translate_fn(
                        texts=texts_to_batch,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        model=model,
                        system_prompt=doc_system_prompt,
                    )
                    if isinstance(batched_outputs, (list, tuple)) and len(batched_outputs) == len(texts_to_batch):
                        for src, tgt in zip(texts_to_batch, batched_outputs):
                            if isinstance(tgt, str):
                                trans_memo[src] = harmonizer.harmonize(tgt, trans_direction)
                except DoshError as err:
                    if err.code in (FailureCode.RESOURCE_UNAVAILABLE, FailureCode.SECURITY_DENIED):
                        raise
                except Exception:
                    # Graceful fallback to on-demand translate_fn if batch call fails
                    pass

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

            key = text.strip()
            if key in trans_memo:
                res = trans_memo[key]
                lead = text[: len(text) - len(text.lstrip())]
                trail = text[len(text.rstrip()) :]
                return f"{lead}{res}{trail}"

            if text in trans_memo:
                return trans_memo[text]

            # Canonical callback contract: invoke translate_fn with document system prompt
            res = translate_fn(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                model=model,
                system_prompt=doc_system_prompt,
            )
            harmonized = harmonizer.harmonize(res, trans_direction)
            trans_memo[text] = harmonized
            trans_memo[key] = harmonized.strip()
            return harmonized

        metadata_updates: dict[str, Any] = {
            "model": model,
            "direction": f"{source_lang}->{target_lang}",
            "provider": provider_id,
            "legal_context": doc_legal_context.to_dict(),
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

                def _docx_batch_runner(batch: list[str]) -> list[str]:
                    if not batch:
                        return []
                    if batch_translate_fn is not None:
                        uncached = [s.strip() for s in batch if s.strip() and s.strip() not in trans_memo and not is_structural_placeholder(s)]
                        if uncached:
                            try:
                                batched = batch_translate_fn(
                                    texts=uncached,
                                    source_lang=source_lang,
                                    target_lang=target_lang,
                                    model=model,
                                    system_prompt=doc_system_prompt,
                                )
                                if isinstance(batched, (list, tuple)) and len(batched) == len(uncached):
                                    for orig, trans in zip(uncached, batched):
                                        if isinstance(trans, str):
                                            trans_memo[orig] = harmonizer.harmonize(trans, trans_direction)
                            except Exception:
                                pass
                    return [_call_translate(s) for s in batch]

                docx_payload = transform_docx_translation_artifact(
                    docx_bytes,
                    translate_fn=_docx_batch_runner,
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

        all_provenance.append(
            ProvenanceRecord(
                source_input_id=doc_or_str.source_input_id if isinstance(doc_or_str, CanonicalDocument) else None,
                capability_id=capability_id,
                evidence={
                    "model": model,
                    "direction": f"{source_lang}->{target_lang}",
                    "provider": provider_id,
                    "legal_context": doc_legal_context.to_dict(),
                },
            )
        )

    output_data = translated_docs[0] if len(docs_to_translate) == 1 else tuple(translated_docs)

    return Result(
        data=output_data,
        artifact_payloads=tuple(all_payloads),
        provenance=tuple(all_provenance),
    )
