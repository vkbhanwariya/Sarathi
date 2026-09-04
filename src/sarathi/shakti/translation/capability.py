"""Executable Translation Capability for Sarathi V2."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Mapping

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ExecutionContext,
    ProvenanceRecord,
    Request,
    Result,
    WarningRecord,
)
from sarathi.sankalpa.document import transform_canonical_document
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.engine import (
    CTranslate2TranslationEngine,
    TranslatorBackend,
)
from sarathi.shakti.translation.models import TranslationDirection, TranslationResult
from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.translation.protector import TranslationProtector


class TranslationCapability:
    """Canonical executable capability for bilingual document translation."""

    def __init__(
        self,
        darpana: Darpana | None = None,
        data_root: Path | None = None,
        backend: TranslatorBackend | None = None,
        engine: CTranslate2TranslationEngine | None = None,
    ) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._detector = LanguageDetector()
        self._protector = TranslationProtector()
        self._engine = engine if engine is not None else CTranslate2TranslationEngine(
            data_root=data_root,
            backend=backend,
            protector=self._protector,
        )

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute translation on prior CanonicalDocument(s) or return appropriate handoff."""
        if prior_result is None or prior_result.data is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="TranslationCapability requires a prior Result containing a CanonicalDocument or sequence of CanonicalDocuments.",
            )

        if isinstance(prior_result.data, CanonicalDocument):
            docs = [prior_result.data]
        elif isinstance(prior_result.data, (tuple, list)) and all(
            isinstance(d, CanonicalDocument) for d in prior_result.data
        ):
            docs = list(prior_result.data)
        else:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="TranslationCapability requires a prior Result containing a CanonicalDocument or sequence of CanonicalDocuments.",
            )

        # If any document text, pages, and tables are completely empty, request OCR continuation through Pravaha
        if any(
            not d.text.strip()
            and not d.tables
            and not any(p.text.strip() or p.tables for p in d.pages)
            for d in docs
        ):
            return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

        # Check if text contains legacy non-Unicode font encoding -> hand off to font_conversion
        for doc in docs:
            full_text = doc.text
            if not full_text.strip() and doc.tables:
                table_lines = []
                for t in doc.tables:
                    if t.headers:
                        table_lines.append(" ".join(str(c) for c in t.headers))
                    for r in t.rows:
                        table_lines.append(" ".join(str(c) for c in r))
                full_text = "\n".join(table_lines)
            if not full_text.strip() and doc.pages:
                full_text = "\n".join(p.text for p in doc.pages if p.text)

            if self._detector.is_legacy_font(full_text):
                return Result(
                    data=prior_result.data,
                    next_requirement="font_conversion",
                    resume_self=True,
                    warnings=(
                        WarningRecord(
                            code="LEGACY_FONT_DETECTED",
                            message="Legacy font encoding detected in input. Escalating to font_conversion.",
                            stage="translation",
                        ),
                    ),
                )

        translated_docs: list[CanonicalDocument] = []
        payloads: list[ArtifactPayload] = []
        provs: list[ProvenanceRecord] = list(prior_result.provenance)
        all_warnings: list[WarningRecord] = list(prior_result.warnings) if prior_result and prior_result.warnings else []

        for idx, doc in enumerate(docs):
            full_text = doc.text
            if not full_text.strip() and doc.tables:
                table_lines = []
                for t in doc.tables:
                    if t.headers:
                        table_lines.append(" ".join(str(c) for c in t.headers))
                    for r in t.rows:
                        table_lines.append(" ".join(str(c) for c in r))
                full_text = "\n".join(table_lines)
            if not full_text.strip() and doc.pages:
                full_text = "\n".join(p.text for p in doc.pages if p.text)

            req_direction = request.metadata.get("direction") if request.metadata else None
            direction = self._detector.resolve_direction(
                full_text, requested_direction=str(req_direction) if req_direction else None
            )

            scope = (
                self._darpana.time_scope(context=context, phase_name="translation", component="shakti.translation")
                if self._darpana
                else nullcontext()
            )
            with scope:
                translation_cache: dict[str, TranslationResult] = {}

                def _trans_text(raw: str) -> str:
                    if not raw or not raw.strip():
                        return raw
                    if raw not in translation_cache:
                        translation_cache[raw] = self._engine.translate(
                            raw, direction=direction, execution_binding=context.execution_binding
                        )
                    return translation_cache[raw].translated_text

                tgt_lang = "en" if direction == TranslationDirection.HI_TO_EN else "hi"
                tgt_script = "Latn" if direction == TranslationDirection.HI_TO_EN else "Deva"

                translated_doc = transform_canonical_document(
                    doc,
                    _trans_text,
                    detected_type="translated_document",
                    target_lang=tgt_lang,
                    target_script=tgt_script,
                )
                translated_docs.append(translated_doc)

                primary_res = translation_cache.get(doc.text) or (
                    next(iter(translation_cache.values())) if translation_cache else None
                )
                src_lang_val = (
                    primary_res.source_language.value
                    if primary_res
                    else ("hi" if direction == TranslationDirection.HI_TO_EN else "en")
                )
                tgt_lang_val = (
                    primary_res.target_language.value
                    if primary_res
                    else ("en" if direction == TranslationDirection.HI_TO_EN else "hi")
                )
                prot_count = sum(r.protected_spans_count for r in translation_cache.values())
                device_val = (
                    primary_res.metadata.get("device", "cpu")
                    if primary_res and isinstance(primary_res.metadata, Mapping)
                    else "cpu"
                )

                prov = ProvenanceRecord(
                    source_input_id=doc.source_input_id,
                    capability_id="translation",
                    stage="translation",
                    evidence={
                        "direction": direction.value,
                        "source_language": src_lang_val,
                        "target_language": tgt_lang_val,
                        "protected_spans_count": prot_count,
                        "device": device_val,
                        "backend": "ctranslate2",
                    },
                )
                provs.append(prov)

                suffix = f"_{idx + 1}" if len(docs) > 1 else ""
                txt_payload = ArtifactPayload(
                    intent=ArtifactIntent(
                        name=f"Translated_Document{suffix}.txt",
                        role="translated_text",
                        media_type="text/plain",
                    ),
                    content=translated_doc.text.encode("utf-8"),
                )
                docx_payload = build_docx_payload(
                    doc=translated_doc,
                    filename=f"Translated_Document{suffix}.docx",
                    role="translated_document",
                )
                payloads.extend([txt_payload, docx_payload])

        result_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)
        return Result(
            data=result_data,
            artifact_payloads=tuple(payloads),
            confidence=None,
            provenance=tuple(provs),
            warnings=tuple(all_warnings),
        )
