"""Executable Translation Capability for Sarathi."""

from __future__ import annotations

import time
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode

if TYPE_CHECKING:
    from sarathi.yantra import Yantra
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ExecutionContext,
    InputRef,
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
from sarathi.shakti.translation.typography import (
    contains_devanagari,
    normalize_size,
    output_font,
)


class TranslationCapability:
    """Canonical executable capability for bilingual document translation."""

    def __init__(
        self,
        darpana: Darpana | None = None,
        data_root: Path | None = None,
        backend: TranslatorBackend | None = None,
        engine: CTranslate2TranslationEngine | None = None,
        yantra: Yantra | None = None,
    ) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._yantra = yantra
        self._detector = LanguageDetector()
        self._protector = TranslationProtector()
        self._engine = engine if engine is not None else CTranslate2TranslationEngine(
            data_root=data_root,
            backend=backend,
            protector=self._protector,
        )

    def _record_telemetry(
        self,
        context: ExecutionContext,
        doc: CanonicalDocument,
        naming_inp: InputRef,
        duration_ns: int | None = None,
    ) -> None:
        """Record worker execution performance and page/region quality telemetry in Darpana."""
        if self._darpana is None:
            return
        from datetime import datetime, timezone

        from sarathi.darpana import MarutiRecord, PramanaRecord

        now_iso = datetime.now(timezone.utc).isoformat()
        dev_t = context.execution_binding.device_type.value.upper() if context.execution_binding else "CPU"
        dev_i = str(context.execution_binding.device_id) if context.execution_binding else "0"
        pages = doc.pages or ()

        if duration_ns is not None:
            self._darpana.record_maruti(
                MarutiRecord(
                    run_id=context.run_id,
                    request_id=context.request_id,
                    trace_id=context.trace_id,
                    span_id=context.span_id,
                    phase_name="worker_execution",
                    component="shakti.translation",
                    timestamp_utc=now_iso,
                    duration_ns=duration_ns,
                    outcome="success",
                    attributes={
                        "worker_id": f"{dev_t.lower()}-worker-{dev_i}",
                        "device_type": dev_t,
                        "device_id": dev_i,
                        "pages_processed": max(1, len(pages)),
                        "file_display_name": naming_inp.display_name,
                    },
                )
            )
        for p in pages:
            self._darpana.record_pramana(
                PramanaRecord(
                    run_id=context.run_id,
                    request_id=context.request_id,
                    trace_id=context.trace_id,
                    span_id=context.span_id,
                    capability_id="translation",
                    stage="translation",
                    timestamp_utc=now_iso,
                    subject_id=f"{doc.document_id}:p{p.page_number}",
                    confidence=None,
                    attributes={
                        "level": "page",
                        "page_number": p.page_number,
                        "file_display_name": naming_inp.display_name,
                        "region_count": len(p.spans),
                        "min_confidence": None,
                        "max_confidence": None,
                    },
                )
            )
            for s_idx, span in enumerate(p.spans[:30]):
                self._darpana.record_pramana(
                    PramanaRecord(
                        run_id=context.run_id,
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        span_id=context.span_id,
                        capability_id="translation",
                        stage="translation",
                        timestamp_utc=now_iso,
                        subject_id=f"{doc.document_id}:p{p.page_number}:s{s_idx}",
                        confidence=None,
                        attributes={
                            "level": "region",
                            "region_id": f"p{p.page_number}_span_{s_idx + 1}",
                            "page_number": p.page_number,
                            "file_display_name": naming_inp.display_name,
                            "region_type": "text",
                        },
                    )
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

        progress_cb = None
        if request.custom_options and callable(request.custom_options.get("progress_callback")):
            progress_cb = request.custom_options["progress_callback"]

        def _process_single_doc(
            idx: int,
            doc: CanonicalDocument,
        ) -> tuple[CanonicalDocument, ProvenanceRecord, list[ArtifactPayload]]:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            if progress_cb is not None:
                dev_str = context.execution_binding.device_type.value.upper() if context.execution_binding else "CPU"
                tot_pages = len(doc.pages) if doc.pages else 1
                progress_cb(
                    file_display_name=doc.document_id,
                    page_number=1,
                    total_pages=tot_pages,
                    worker_id=str(idx + 1),
                    stage="Machine Translation",
                    device_type=dev_str,
                    input_id=doc.document_id,
                )

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
                t_trans_start = time.perf_counter_ns()
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
                trans_dur_ns = max(0, time.perf_counter_ns() - t_trans_start)

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

                matching_inp = next((i for i in request.inputs if i.input_id == doc.source_input_id), None)
                naming_inp = matching_inp or InputRef(
                    input_id=doc.source_input_id or doc.document_id,
                    source_path=Path(f"{doc.document_id}.txt"),
                    display_name=doc.document_id,
                    size_bytes=0,
                )
                self._record_telemetry(context, translated_doc, naming_inp, duration_ns=trans_dur_ns)

                suffix = f"_{idx + 1}" if len(docs) > 1 else ""
                txt_payload = ArtifactPayload(
                    intent=ArtifactIntent(
                        name=f"Translated_Document{suffix}.txt",
                        role="translated_text",
                        media_type="text/plain",
                    ),
                    content=translated_doc.text.encode("utf-8"),
                )
                doc_has_dev = contains_devanagari(translated_doc.text) or (tgt_lang == "hi")
                doc_font = output_font(contains_devanagari=doc_has_dev)
                raw_size = doc.metadata.get("font_size_pt") if doc.metadata else None
                doc_size = normalize_size(raw_size)
                docx_payload = build_docx_payload(
                    doc=translated_doc,
                    filename=f"Translated_Document{suffix}.docx",
                    role="translated_document",
                    default_font=doc_font,
                    default_size_pt=doc_size,
                )
                return translated_doc, prov, [txt_payload, docx_payload]

        is_parallelizable = self.declaration.device_requirement.parallelizable
        if len(docs) > 1 and self._yantra is not None and is_parallelizable:
            def _make_task(
                i: int, d: CanonicalDocument
            ) -> Callable[[], tuple[CanonicalDocument, ProvenanceRecord, list[ArtifactPayload]]]:
                return lambda: _process_single_doc(i, d)

            subtasks = [_make_task(idx, doc) for idx, doc in enumerate(docs)]
            task_results = self._yantra.execute_subtasks(subtasks, context=context)
            for t_doc, t_prov, t_payloads in task_results:
                translated_docs.append(t_doc)
                provs.append(t_prov)
                payloads.extend(t_payloads)
        else:
            for idx, doc in enumerate(docs):
                t_doc, t_prov, t_payloads = _process_single_doc(idx, doc)
                translated_docs.append(t_doc)
                provs.append(t_prov)
                payloads.extend(t_payloads)

        result_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)
        return Result(
            data=result_data,
            artifact_payloads=tuple(payloads),
            confidence=None,
            provenance=tuple(provs),
            warnings=tuple(all_warnings),
        )
