"""Executable Translation Capability for Sarathi."""

from __future__ import annotations

import re
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode

if TYPE_CHECKING:
    from sarathi.yantra import Yantra
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ExecutionBinding,
    ExecutionContext,
    InputRef,
    ProvenanceRecord,
    Request,
    Result,
    TableData,
    WarningRecord,
    check_cancelled,
)
from sarathi.sankalpa.document import normalize_canonical_documents, transform_canonical_document
from sarathi.shakti.docx_exporter import (
    build_docx_payload,
    transform_docx_translation_artifact,
)
from sarathi.shakti.text import cell_text
from sarathi.shakti.text.typography import (
    contains_devanagari,
    normalize_size,
    output_font,
)
from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.engine import (
    CTranslate2TranslationEngine,
    TranslatorBackend,
)
from sarathi.shakti.translation.legal_context import LegalContextBuilder
from sarathi.shakti.translation.models import TranslationDirection, TranslationResult
from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.translation.protector import TranslationProtector

_STRUCTURAL_TAG_RE: re.Pattern[str] = re.compile(
    r"^(?:\{\{[A-Z_]+:[^}]+\}\}|<!--\s*[A-Z_]+:[^>]+-->|\[[A-Z_]+:[^\]]+\]|---\s*Page\s*\d+\s*---)$",
    re.IGNORECASE,
)
_STRUCTURAL_SPLIT_RE: re.Pattern[str] = re.compile(
    r"(\{\{[A-Z_]+:[^}]+\}\}|<!--\s*[A-Z_]+:[^>]+-->|\[[A-Z_]+:[^\]]+\]|---\s*Page\s*\d+\s*---)",
    re.IGNORECASE,
)


def _collect_document_texts(doc: CanonicalDocument) -> list[str]:
    """Pre-collect all unique non-empty text strings across document structure."""
    unique_texts: list[str] = []
    seen_texts: set[str] = set()

    def _collect(s: str | None) -> None:
        if not s or not s.strip():
            return
        if _is_structural_placeholder(s):
            return
        if "{{" in s and ("{{TABLE:" in s or "{{PAGE:" in s):
            for chunk in _STRUCTURAL_SPLIT_RE.split(s):
                if chunk.strip() and not _is_structural_placeholder(chunk) and chunk not in seen_texts:
                    seen_texts.add(chunk)
                    unique_texts.append(chunk)
        elif s not in seen_texts:
            seen_texts.add(s)
            unique_texts.append(s)

    if not doc.pages:
        _collect(doc.text)
    for t in doc.tables:
        if t.headers:
            for h in t.headers:
                _collect(cell_text(h))
        for r in t.rows:
            for c in r:
                _collect(cell_text(c))
    for p in doc.pages:
        _collect(p.text)
        for s in p.spans:
            _collect(s.text)
        for t in p.tables:
            if t.headers:
                for h in t.headers:
                    _collect(cell_text(h))
            for r in t.rows:
                for c in r:
                    _collect(cell_text(c))
    return unique_texts


def _check_translation_handoffs(
    docs: Sequence[CanonicalDocument],
    prior_result: Result,
    detector: LanguageDetector,
) -> Result | None:
    """Evaluate whether inputs require OCR fallback or legacy font conversion handoff."""
    if any(
        not d.text.strip() and not d.tables and not any(p.text.strip() or p.tables for p in d.pages) for d in docs
    ):
        return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

    for doc in docs:
        full_text = doc.text
        if not full_text.strip() and doc.tables:
            table_lines = []
            for t in doc.tables:
                if t.headers:
                    table_lines.append(" ".join(cell_text(c) for c in t.headers if cell_text(c)))
                for r in t.rows:
                    table_lines.append(" ".join(cell_text(c) for c in r if cell_text(c)))
            full_text = "\n".join(table_lines)
        if not full_text.strip() and doc.pages:
            full_text = "\n".join(p.text for p in doc.pages if p.text)

        if detector.is_legacy_font(full_text):
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
    return None


def _is_structural_placeholder(text: str | None) -> bool:
    """Return True if text is purely an internal structural tag or page separator."""
    if not text:
        return False
    return bool(_STRUCTURAL_TAG_RE.match(text.strip()))


def _format_table_as_markdown(table: TableData) -> str:
    """Format a TableData instance as readable GitHub-flavored markdown."""
    lines: list[str] = []
    if table.name and not table.name.startswith("Table_") and not table.name.startswith("Page_"):
        lines.append(f"### {table.name}\n")
    if table.headers:
        lines.append("| " + " | ".join(cell_text(c) for c in table.headers) + " |")
        lines.append("| " + " | ".join("---" for _ in table.headers) + " |")
    for row in table.rows:
        lines.append("| " + " | ".join(cell_text(c) for c in row) + " |")
    return "\n".join(lines)


def _format_translated_document_text(doc: CanonicalDocument) -> str:
    """Format translated document text for plaintext export, serializing tables cleanly."""
    if not doc.tables:
        return doc.text

    table_map: dict[str, TableData] = {}
    for idx, tbl in enumerate(doc.tables, 1):
        if tbl.name:
            table_map[tbl.name.strip().lower()] = tbl
        table_map[f"table_{idx}"] = tbl
        table_map[f"table {idx}"] = tbl

    rendered_tables: set[int] = set()

    from sarathi.shakti.docx_exporter.builder import _TABLE_ANCHOR_RE

    def _replace_anchor(match: re.Match[str]) -> str:
        name = (match.group(1) or match.group(2) or match.group(3)).strip().lower()
        tbl = table_map.get(name)
        if tbl is not None:
            rendered_tables.add(id(tbl))
            return "\n\n" + _format_table_as_markdown(tbl) + "\n\n"
        return match.group(0)

    formatted = _TABLE_ANCHOR_RE.sub(_replace_anchor, doc.text)

    unrendered = [t for t in doc.tables if id(t) not in rendered_tables]
    if unrendered:
        parts = [formatted.strip()] if formatted.strip() and formatted.strip() != doc.text.strip() else []
        for t in unrendered:
            parts.append(_format_table_as_markdown(t))
        if parts:
            formatted = "\n\n".join(parts)

    return formatted.strip() if formatted.strip() else doc.text


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
        self._engine = (
            engine
            if engine is not None
            else CTranslate2TranslationEngine(
                data_root=data_root,
                backend=backend,
                protector=self._protector,
            )
        )
        self._legal_builder = LegalContextBuilder(glossary_store=getattr(self._engine, "_glossary", None))

    @property
    def asset_version(self) -> str:
        return getattr(self._engine, "asset_version", "")

    def warmup(self, execution_binding: ExecutionBinding | None = None) -> bool:
        """Pre-initialize translation engine and neural models."""
        if hasattr(self._engine, "warmup"):
            return bool(self._engine.warmup(execution_binding=execution_binding))
        return False

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

        docs = normalize_canonical_documents(prior_result.data)
        if docs is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="TranslationCapability requires a prior Result containing a CanonicalDocument or sequence of CanonicalDocuments.",
            )

        handoff = _check_translation_handoffs(docs, prior_result, self._detector)
        if handoff is not None:
            return handoff

        translated_docs: list[CanonicalDocument] = []
        payloads: list[ArtifactPayload] = []
        provs: list[ProvenanceRecord] = list(prior_result.provenance)
        all_warnings: list[WarningRecord] = (
            list(prior_result.warnings) if prior_result and prior_result.warnings else []
        )

        progress_cb = None
        if request.custom_options and callable(request.custom_options.get("progress_callback")):
            progress_cb = request.custom_options["progress_callback"]

        def _process_single_doc(
            idx: int,
            doc: CanonicalDocument,
        ) -> tuple[CanonicalDocument, ProvenanceRecord, list[ArtifactPayload]]:
            check_cancelled(context)

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

            sample_parts: list[str] = [doc.text] if doc.text else []
            if doc.tables:
                for t in doc.tables:
                    if t.headers:
                        sample_parts.append(" ".join(cell_text(c) for c in t.headers if cell_text(c)))
                    for r in t.rows:
                        sample_parts.append(" ".join(cell_text(c) for c in r if cell_text(c)))
            if doc.pages:
                for p in doc.pages:
                    if p.text:
                        sample_parts.append(p.text)
                    for s in p.spans:
                        if s.text:
                            sample_parts.append(s.text)
                    for t in p.tables:
                        if t.headers:
                            sample_parts.append(" ".join(cell_text(c) for c in t.headers if cell_text(c)))
                        for r in t.rows:
                            sample_parts.append(" ".join(cell_text(c) for c in r if cell_text(c)))
            combined_text = "\n".join(sample_parts) if sample_parts else doc.text

            req_direction = (
                request.metadata.get("direction")
                if request.metadata
                else (request.custom_options.get("direction") if request.custom_options else None)
            )
            req_engine = (
                str(request.custom_options.get("engine", "indictrans2")).lower().strip()
                if request.custom_options
                else "indictrans2"
            )
            direction = self._detector.resolve_direction(
                combined_text, requested_direction=str(req_direction) if req_direction else None
            )

            # Extract domain legal context, dynamic glossary candidates, and statutory citations
            legal_context = self._legal_builder.extract_context(
                text=combined_text,
                direction=direction,
                custom_options=request.custom_options,
                max_glossary_terms=100,
            )
            verbatim_citations: list[str] = []
            if legal_context.cnr_number:
                verbatim_citations.append(legal_context.cnr_number)
            if legal_context.case_number:
                verbatim_citations.append(legal_context.case_number)
            for ref in legal_context.statutory_references:
                if direction == TranslationDirection.HI_TO_EN and contains_devanagari(ref):
                    continue
                if any(k in ref for k in ("SCC", "AIR", "INSC", "ILR", "FIR", "Crime No", "CNR", "W.P.", "Crl.A.")):
                    verbatim_citations.append(ref)
                elif direction == TranslationDirection.EN_TO_HI and not contains_devanagari(ref):
                    verbatim_citations.append(ref)

            active_glossary = legal_context.matched_glossary_terms

            def _call_engine_translate_single(text_s: str) -> TranslationResult:
                return self._engine.translate(
                    text_s,
                    direction=direction,
                    execution_binding=context.execution_binding,
                    engine=req_engine,
                    glossary_terms=active_glossary,
                    custom_terms=verbatim_citations,
                )

            def _call_engine_translate_batch(batch: Sequence[str]) -> list[TranslationResult]:
                if hasattr(self._engine, "translate_batch"):
                    return self._engine.translate_batch(
                        batch,
                        direction=direction,
                        execution_binding=context.execution_binding,
                        engine=req_engine,
                        glossary_terms=active_glossary,
                        custom_terms=verbatim_citations,
                    )
                return [_call_engine_translate_single(s) for s in batch]

            scope = (
                self._darpana.time_scope(context=context, phase_name="translation", component="shakti.translation")
                if self._darpana
                else nullcontext()
            )
            with scope:
                t_trans_start = time.perf_counter_ns()
                translation_cache: dict[str, TranslationResult] = {}

                unique_texts = _collect_document_texts(doc)

                # 2. Batch-translate all unique texts in a single pass to saturate all CPU P-cores
                if unique_texts:
                    batch_results = _call_engine_translate_batch(unique_texts)
                    for raw_s, res in zip(unique_texts, batch_results):
                        translation_cache[raw_s] = res

                # 3. Transform document with instant O(1) cache lookups
                def _trans_text(raw: str) -> str:
                    if not raw or not raw.strip():
                        return raw
                    if _is_structural_placeholder(raw):
                        return raw
                    if "{{" in raw and ("{{TABLE:" in raw or "{{PAGE:" in raw):
                        chunks = _STRUCTURAL_SPLIT_RE.split(raw)
                        translated_chunks: list[str] = []
                        for c in chunks:
                            if _is_structural_placeholder(c):
                                translated_chunks.append(c)
                            elif c.strip():
                                translated_chunks.append(_trans_text(c))
                            else:
                                translated_chunks.append(c)
                        return "".join(translated_chunks)
                    if raw not in translation_cache:
                        translation_cache[raw] = _call_engine_translate_single(raw)
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
                meta = dict(translated_doc.metadata) if translated_doc.metadata else {}
                meta["legal_context"] = legal_context.to_dict()
                translated_doc = replace(translated_doc, metadata=meta)
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
                        "engine": req_engine,
                        "legal_context": legal_context.to_dict(),
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
                    content=_format_translated_document_text(translated_doc).encode("utf-8"),
                )
                doc_has_dev = contains_devanagari(translated_doc.text) or (tgt_lang == "hi")
                doc_font = output_font(contains_devanagari=doc_has_dev)
                raw_size = doc.metadata.get("font_size_pt") if doc.metadata else None
                doc_size = normalize_size(raw_size)
                docx_payload = None
                if (
                    matching_inp
                    and matching_inp.source_path
                    and str(matching_inp.source_path).lower().endswith(".docx")
                ):
                    try:

                        def _batch_trans(batch: list[str]) -> list[str]:
                            missing = [
                                t
                                for t in set(batch)
                                if t and t.strip() and not _is_structural_placeholder(t) and t not in translation_cache
                            ]
                            if missing:
                                b_res = _call_engine_translate_batch(missing)
                                for raw_t, r in zip(missing, b_res):
                                    translation_cache[raw_t] = r
                            return [_trans_text(t) for t in batch]

                        docx_bytes = matching_inp.source_path.read_bytes()
                        docx_payload = transform_docx_translation_artifact(
                            docx_bytes,
                            translate_fn=_batch_trans,
                            filename=f"Translated_Document{suffix}.docx",
                            role="translated_document",
                        )
                    except Exception:
                        docx_payload = None

                if docx_payload is None:
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
