"""Executable Translation Capability for Sarathi."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sarathi.darpana import Darpana
from sarathi.dosh import DoshError, FailureCode

if TYPE_CHECKING:
    from sarathi.yantra import Yantra
from datetime import UTC

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
)
from sarathi.sankalpa.cancellation import check_cancelled
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
from sarathi.shakti.translation.xlsx_transformer import (
    build_xlsx_from_tables,
    transform_xlsx_translation_artifact,
)

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
    if any(not d.text.strip() and not d.tables and not any(p.text.strip() or p.tables for p in d.pages) for d in docs):
        return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

    # Guard against repeated font_conversion escalations in the same pipeline execution
    has_prior_font_conv = (
        (prior_result.provenance and any(p.capability_id == "font_conversion" for p in prior_result.provenance))
        or (prior_result.warnings and any(w.stage == "font_conversion" for w in prior_result.warnings))
        or any(
            bool(d.metadata and (d.metadata.get("font_conversion_applied") or d.metadata.get("converted_docx_bytes")))
            for d in docs
        )
    )
    if has_prior_font_conv:
        return None

    from sarathi.shakti.text.legacy_fonts import load_font_profiles, resolve_profile_from_font_name

    profiles = load_font_profiles()

    for doc in docs:
        # 1. Check doc.text directly
        if doc.text and detector.is_legacy_font(doc.text):
            return Result(
                data=prior_result.data,
                next_requirement="font_conversion",
                resume_self=True,
                warnings=(
                    WarningRecord(
                        code="LEGACY_FONT_DETECTED",
                        message="Legacy font encoding detected in input text. Escalating to font_conversion.",
                        stage="translation",
                    ),
                ),
            )

        # 2. Check all page spans and page text
        for p in doc.pages:
            if p.text and detector.is_legacy_font(p.text):
                return Result(
                    data=prior_result.data,
                    next_requirement="font_conversion",
                    resume_self=True,
                    warnings=(
                        WarningRecord(
                            code="LEGACY_FONT_DETECTED",
                            message="Legacy font encoding detected in page text. Escalating to font_conversion.",
                            stage="translation",
                        ),
                    ),
                )
            for s in p.spans:
                if s.text and detector.is_legacy_font(s.text):
                    return Result(
                        data=prior_result.data,
                        next_requirement="font_conversion",
                        resume_self=True,
                        warnings=(
                            WarningRecord(
                                code="LEGACY_FONT_DETECTED",
                                message="Legacy font encoding detected in span text. Escalating to font_conversion.",
                                stage="translation",
                            ),
                        ),
                    )
                if s.metadata and s.metadata.get("font_name"):
                    p_id, fam = resolve_profile_from_font_name(s.metadata["font_name"], profiles)
                    if p_id is not None or fam == "unsupported_legacy":
                        return Result(
                            data=prior_result.data,
                            next_requirement="font_conversion",
                            resume_self=True,
                            warnings=(
                                WarningRecord(
                                    code="LEGACY_FONT_DETECTED",
                                    message=f"Legacy font '{s.metadata['font_name']}' detected in document span. Escalating to font_conversion.",
                                    stage="translation",
                                ),
                            ),
                        )

        # 3. Check all table headers and cells
        all_tables = list(doc.tables) + [t for p in doc.pages for t in p.tables]
        for tbl in all_tables:
            for h in tbl.headers:
                txt = cell_text(h)
                if txt and detector.is_legacy_font(txt):
                    return Result(
                        data=prior_result.data,
                        next_requirement="font_conversion",
                        resume_self=True,
                        warnings=(
                            WarningRecord(
                                code="LEGACY_FONT_DETECTED",
                                message="Legacy font encoding detected in table header. Escalating to font_conversion.",
                                stage="translation",
                            ),
                        ),
                    )
            for r in tbl.rows:
                for c in r:
                    txt = cell_text(c)
                    if txt and detector.is_legacy_font(txt):
                        return Result(
                            data=prior_result.data,
                            next_requirement="font_conversion",
                            resume_self=True,
                            warnings=(
                                WarningRecord(
                                    code="LEGACY_FONT_DETECTED",
                                    message="Legacy font encoding detected in table cell. Escalating to font_conversion.",
                                    stage="translation",
                                ),
                            ),
                        )
            if tbl.metadata and tbl.metadata.get("cell_fonts"):
                for row_fonts in tbl.metadata["cell_fonts"]:
                    for f in row_fonts:
                        if f:
                            p_id, fam = resolve_profile_from_font_name(f, profiles)
                            if p_id is not None or fam == "unsupported_legacy":
                                return Result(
                                    data=prior_result.data,
                                    next_requirement="font_conversion",
                                    resume_self=True,
                                    warnings=(
                                        WarningRecord(
                                            code="LEGACY_FONT_DETECTED",
                                            message=f"Legacy font '{f}' detected in table cell. Escalating to font_conversion.",
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

    def warmup(
        self,
        execution_binding: ExecutionBinding | None = None,
        directions: Sequence[TranslationDirection] = (TranslationDirection.HI_TO_EN, TranslationDirection.EN_TO_HI),
        engine: str = "krutrim",
    ) -> bool:
        """Pre-initialize translation engine and dual neural models into RAM."""
        if hasattr(self._engine, "warmup"):
            return bool(self._engine.warmup(execution_binding=execution_binding, directions=directions, engine=engine))
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
        from datetime import datetime

        from sarathi.darpana import MarutiRecord, PramanaRecord

        now_iso = datetime.now(UTC).isoformat()
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
        ) -> tuple[CanonicalDocument, ProvenanceRecord, list[ArtifactPayload], list[WarningRecord]]:
            check_cancelled(context)
            doc_warnings: list[WarningRecord] = []

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
                str(request.custom_options.get("engine", "krutrim")).lower().strip()
                if request.custom_options
                else "krutrim"
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

            import inspect

            def _takes_profile(func: Any) -> bool:
                try:
                    sig = inspect.signature(func)
                    return "execution_profile" in sig.parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                    )
                except (ValueError, TypeError):
                    return True

            single_takes_prof = (
                _takes_profile(self._engine.translate) if hasattr(self._engine, "translate") else False
            )
            batch_takes_prof = (
                _takes_profile(self._engine.translate_batch) if hasattr(self._engine, "translate_batch") else False
            )

            def _call_engine_translate_single(text_s: str) -> TranslationResult:
                kwargs: dict[str, Any] = {
                    "direction": direction,
                    "execution_binding": context.execution_binding,
                    "engine": req_engine,
                    "glossary_terms": active_glossary,
                    "custom_terms": verbatim_citations,
                }
                if single_takes_prof:
                    kwargs["execution_profile"] = context.profile
                return self._engine.translate(text_s, **kwargs)

            def _call_engine_translate_batch(batch: Sequence[str]) -> list[TranslationResult]:
                if hasattr(self._engine, "translate_batch"):
                    kwargs: dict[str, Any] = {
                        "direction": direction,
                        "execution_binding": context.execution_binding,
                        "engine": req_engine,
                        "glossary_terms": active_glossary,
                        "custom_terms": verbatim_citations,
                    }
                    if batch_takes_prof:
                        kwargs["execution_profile"] = context.profile
                    return self._engine.translate_batch(batch, **kwargs)
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
                docx_source_path = None
                docx_bytes = None
                if doc.metadata and doc.metadata.get("converted_docx_bytes"):
                    docx_bytes = doc.metadata["converted_docx_bytes"]
                elif doc.metadata and doc.metadata.get("converted_docx_path"):
                    p = Path(doc.metadata["converted_docx_path"])
                    if p.is_file():
                        docx_source_path = p
                elif (
                    matching_inp
                    and matching_inp.source_path
                    and str(matching_inp.source_path).lower().endswith(".docx")
                    and matching_inp.source_path.is_file()
                ):
                    docx_source_path = matching_inp.source_path

                def _batch_trans(batch: list[str]) -> list[str]:
                    missing = [
                        t
                        for t in set(batch)
                        if t and t.strip() and not _is_structural_placeholder(t) and t not in translation_cache
                    ]
                    if missing:
                        b_res = _call_engine_translate_batch(missing)
                        if len(b_res) != len(missing):
                            raise DoshError(
                                code=FailureCode.EXECUTION_FAILED,
                                message=f"Batch translation count mismatch: expected {len(missing)}, got {len(b_res)}",
                            )
                        for raw_t, r in zip(missing, b_res, strict=True):
                            translation_cache[raw_t] = r
                    return [_trans_text(t) for t in batch]

                if docx_bytes is not None or docx_source_path is not None:
                    try:
                        raw_docx_bytes = docx_bytes if docx_bytes is not None else docx_source_path.read_bytes()

                        # Ensure source docx is normalized to Unicode if legacy font signatures remain
                        try:
                            from sarathi.shakti.docx_exporter import transform_docx_artifact
                            from sarathi.shakti.font_conversion.capability import FontConversionCapability
                            from sarathi.shakti.text.legacy_fonts import resolve_profile_from_font_name

                            fc = FontConversionCapability()
                            norm_payload = transform_docx_artifact(
                                input_bytes=raw_docx_bytes,
                                converter_fn=lambda raw, font_name=None, **kw: (
                                    fc._converter.convert(
                                        raw,
                                        profile_id=resolve_profile_from_font_name(font_name, fc._profiles)[0]
                                        or "krutidev010",
                                    )
                                    if font_name and resolve_profile_from_font_name(font_name, fc._profiles)[0]
                                    else (
                                        fc._converter.convert(raw, profile_id="krutidev010")
                                        if fc._detector.is_legacy_text(raw)
                                        else raw
                                    )
                                ),
                                filename=f"Normalized_{suffix}.docx",
                                role="converted_document",
                                preserve_typography=True,
                                profiles=fc._profiles,
                                profile_resolver=resolve_profile_from_font_name,
                            )
                            raw_docx_bytes = norm_payload.content
                        except Exception:
                            pass

                        docx_payload = transform_docx_translation_artifact(
                            raw_docx_bytes,
                            translate_fn=_batch_trans,
                            filename=f"Translated_Document{suffix}.docx",
                            role="translated_document",
                            warnings=doc_warnings,
                        )
                    except Exception as exc:
                        doc_warnings.append(
                            WarningRecord(
                                code="DOCX_TRANSFORM_FAILED",
                                message=f"Failed in-place DOCX translation, falling back to reconstructed document: {exc}",
                                stage="docx_exporter",
                            )
                        )
                        docx_payload = None

                if docx_payload is None:
                    docx_payload = build_docx_payload(
                        doc=translated_doc,
                        filename=f"Translated_Document{suffix}.docx",
                        role="translated_document",
                        default_font=doc_font,
                        default_size_pt=doc_size,
                    )

                # Process Excel / Spreadsheet translation artifacts
                xlsx_payload = None
                xlsx_source_path = None
                is_spreadsheet_input = (
                    (
                        matching_inp
                        and matching_inp.source_path
                        and str(matching_inp.source_path).lower().endswith((".xlsx", ".xlsm", ".csv", ".tsv", ".xls"))
                        and matching_inp.source_path.is_file()
                    )
                    or doc.detected_type in ("spreadsheet", "csv", "tabular")
                )

                if (
                    matching_inp
                    and matching_inp.source_path
                    and str(matching_inp.source_path).lower().endswith((".xlsx", ".xlsm"))
                    and matching_inp.source_path.is_file()
                ):
                    xlsx_source_path = matching_inp.source_path

                if xlsx_source_path is not None:
                    try:
                        raw_xlsx_bytes = xlsx_source_path.read_bytes()
                        xlsx_payload = transform_xlsx_translation_artifact(
                            raw_xlsx_bytes,
                            translate_fn=_batch_trans,
                            filename=f"Translated_Document{suffix}.xlsx",
                            role="translated_document",
                            warnings=doc_warnings,
                            is_hindi_target=(tgt_lang == "hi"),
                        )
                    except Exception as exc:
                        doc_warnings.append(
                            WarningRecord(
                                code="XLSX_TRANSFORM_FAILED",
                                message=f"Failed in-place XLSX translation: {exc}",
                                stage="xlsx_transformer",
                            )
                        )
                        xlsx_payload = None
                elif is_spreadsheet_input and translated_doc.tables:
                    try:
                        xlsx_payload = build_xlsx_from_tables(
                            tables=translated_doc.tables,
                            filename=f"Translated_Document{suffix}.xlsx",
                            role="translated_document",
                            is_hindi_target=(tgt_lang == "hi"),
                        )
                    except Exception as exc:
                        doc_warnings.append(
                            WarningRecord(
                                code="XLSX_BUILD_FAILED",
                                message=f"Failed building XLSX from translated tables: {exc}",
                                stage="xlsx_transformer",
                            )
                        )
                        xlsx_payload = None

                # Collect span protection and truncation issues across all executed translation results
                for r in translation_cache.values():
                    if not r.metadata:
                        continue
                    span_issues = r.metadata.get("span_protection_issues")
                    if span_issues:
                        for issue in span_issues:
                            if isinstance(issue, str):
                                doc_warnings.append(
                                    WarningRecord(
                                        code=issue,
                                        message=f"Translation span protection issue: {issue}",
                                        stage="translation",
                                    )
                                )
                            elif isinstance(issue, dict):
                                code_str = str(issue.get("code", "PROTECTED_SPAN_ISSUE"))
                                orig = str(issue.get("original_text", ""))
                                doc_warnings.append(
                                    WarningRecord(
                                        code=code_str,
                                        message=f"Protected span issue on '{orig}': {code_str}",
                                        stage="translation",
                                    )
                                )
                    if r.metadata.get("truncation_suspected"):
                        doc_warnings.append(
                            WarningRecord(
                                code="TRANSLATION_TRUNCATION_SUSPECTED",
                                message="Suspected sentence truncation in translation output.",
                                stage="translation",
                            )
                        )
                    if r.metadata.get("input_truncation_suspected"):
                        doc_warnings.append(
                            WarningRecord(
                                code="TRANSLATION_INPUT_TRUNCATED",
                                message="Translation input exceeded token bounds and was truncated.",
                                stage="translation",
                            )
                        )

                delivered_payloads = [txt_payload, docx_payload]
                if xlsx_payload is not None:
                    delivered_payloads.append(xlsx_payload)

                return translated_doc, prov, delivered_payloads, doc_warnings

        is_parallelizable = self.declaration.device_requirement.parallelizable
        if len(docs) > 1 and self._yantra is not None and is_parallelizable:

            def _make_task(
                i: int, d: CanonicalDocument
            ) -> Callable[[], tuple[CanonicalDocument, ProvenanceRecord, list[ArtifactPayload], list[WarningRecord]]]:
                return lambda: _process_single_doc(i, d)

            subtasks = [_make_task(idx, doc) for idx, doc in enumerate(docs)]
            task_results = self._yantra.execute_subtasks(subtasks, context=context)
            for t_doc, t_prov, t_payloads, t_warns in task_results:
                translated_docs.append(t_doc)
                provs.append(t_prov)
                payloads.extend(t_payloads)
                all_warnings.extend(t_warns)
        else:
            for idx, doc in enumerate(docs):
                t_doc, t_prov, t_payloads, t_warns = _process_single_doc(idx, doc)
                translated_docs.append(t_doc)
                provs.append(t_prov)
                payloads.extend(t_payloads)
                all_warnings.extend(t_warns)

        # Deduplicate warnings while preserving order
        unique_warnings: list[WarningRecord] = []
        seen_keys: set[tuple[str, str, str | None]] = set()
        for w in all_warnings:
            key = (w.code, w.message, w.stage)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_warnings.append(w)

        result_data = translated_docs[0] if len(translated_docs) == 1 else tuple(translated_docs)
        return Result(
            data=result_data,
            artifact_payloads=tuple(payloads),
            confidence=None,
            provenance=tuple(provs),
            warnings=tuple(unique_warnings),
        )
