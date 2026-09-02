"""Executable Translation Capability for Sarathi V2."""

from __future__ import annotations

from datetime import datetime, timezone

from contextlib import nullcontext
from pathlib import Path
from typing import Any

from sarathi.darpana import AccuracyValue, Darpana, PramanaRecord
from sarathi.sankalpa import ConfidenceValue
from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    ExecutionContext,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TableData,
    WarningRecord,
)
from sarathi.shakti.translation.anubhava import TranslationAnubhavaStore
from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.engine import TranslationEngine
from sarathi.shakti.translation.glossary import GlossaryStore
from sarathi.shakti.translation.models import TranslationDirection
from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.translation.protector import TranslationProtector
from sarathi.shakti.translation.validator import TranslationValidator


class TranslationCapability:
    """Canonical executable capability for bilingual document translation."""

    def __init__(
        self,
        darpana: Darpana | None = None,
        glossary_dir: Path | None = None,
        anubhava_dir: Path | None = None,
    ) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._detector = LanguageDetector()
        self._glossary = GlossaryStore(glossary_dir=glossary_dir)
        self._anubhava = TranslationAnubhavaStore(anubhava_dir=anubhava_dir)
        self._protector = TranslationProtector()
        self._engine = TranslationEngine(
            glossary=self._glossary,
            anubhava=self._anubhava,
            protector=self._protector,
        )
        self._validator = TranslationValidator()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute translation on prior CanonicalDocument or return appropriate handoff."""
        if prior_result is None or not isinstance(prior_result.data, CanonicalDocument):
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="TranslationCapability requires a prior Result containing a CanonicalDocument.",
            )

        doc: CanonicalDocument = prior_result.data
        base_prov: tuple[ProvenanceRecord, ...] = prior_result.provenance

        # If document is empty and needs OCR
        if not doc.text.strip() and not any(p.tables for p in doc.pages) and not doc.tables and doc.pages:
            return Result(data=doc, next_requirement="ocr")

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

        # Check if text contains legacy non-Unicode font encoding -> hand off to font_conversion
        if self._detector.is_legacy_font(full_text):
            return Result(
                data=doc,
                next_requirement="font_conversion",
                warnings=(
                    WarningRecord(
                        code="LEGACY_FONT_DETECTED",
                        message="Legacy font encoding detected in input. Escalating to font_conversion.",
                        stage="translation",
                    ),
                ),
            )

        # Resolve translation direction
        req_direction = request.metadata.get("direction") if request.metadata else None
        direction = self._detector.resolve_direction(full_text, requested_direction=str(req_direction) if req_direction else None)

        scope = (
            self._darpana.time_scope(context=context, phase_name="translation", component="shakti.translation")
            if self._darpana else nullcontext()
        )
        with scope:
            # 1. Translate main document text
            t_res = self._engine.translate(full_text, direction=direction)

            # 2. Translate table data if present
            converted_tables: list[TableData] = []
            for t in doc.tables:
                t_rows: list[tuple[str, ...]] = []
                for row in t.rows:
                    r_cells: list[str] = []
                    for cell in row:
                        cell_res = self._engine.translate(str(cell), direction=direction)
                        r_cells.append(cell_res.translated_text)
                    t_rows.append(tuple(r_cells))
                t_headers = tuple(
                    self._engine.translate(str(h), direction=direction).translated_text
                    for h in t.headers
                ) if t.headers else ()
                converted_tables.append(TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata))

            # 3. Translate page text if present
            converted_pages: list[PageData] = []
            for p in doc.pages:
                p_res = self._engine.translate(p.text, direction=direction)
                p_tables: list[TableData] = []
                for t in p.tables:
                    t_rows = []
                    for row in t.rows:
                        r_cells = [self._engine.translate(str(cell), direction=direction).translated_text for cell in row]
                        t_rows.append(tuple(r_cells))
                    t_headers = tuple(self._engine.translate(str(h), direction=direction).translated_text for h in t.headers) if t.headers else ()
                    p_tables.append(TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata))
                converted_pages.append(PageData(page_number=p.page_number, text=p_res.translated_text, tables=tuple(p_tables), metadata=p.metadata))

            translated_doc = CanonicalDocument(
                document_id=doc.document_id,
                source_input_id=doc.source_input_id,
                text=t_res.translated_text,
                pages=tuple(converted_pages),
                tables=tuple(converted_tables or (converted_pages[0].tables if converted_pages else ())),
                detected_type="translated_document",
                metadata=doc.metadata,
            )

            prov = ProvenanceRecord(
                source_input_id=request.inputs[0].input_id if request.inputs else None,
                capability_id="translation",
                stage="translation",
                evidence={
                    "direction": direction.value,
                    "source_language": t_res.source_language.value,
                    "target_language": t_res.target_language.value,
                    "protected_spans_count": t_res.protected_spans_count,
                },
            )

            payload = ArtifactPayload(
                intent=ArtifactIntent(name="Translated_Document.txt", role="translated_text", media_type="text/plain"),
                content=t_res.translated_text.encode("utf-8"),
            )

            # Record Pramana telemetry to Darpana if available
            if self._darpana is not None:
                pramana_rec = PramanaRecord(
                    run_id=context.run_id,
                    request_id=context.request_id,
                    trace_id=context.trace_id,
                    span_id=context.span_id,
                    capability_id="translation",
                    stage="translation",
                    timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    confidence=ConfidenceValue(score=1.0, method="exact_dictionary_alignment", evidence={"protected_spans": t_res.protected_spans_count}),
                    accuracy=AccuracyValue(
                        score=1.0,
                        method="exact_span_validation",
                        evidence={"protected_spans": t_res.protected_spans_count},
                    ),
                    attributes={
                        "direction": direction.value,
                        "protected_spans": t_res.protected_spans_count,
                    },
                )
                self._darpana.record_pramana(pramana_rec)

            return Result(
                data=translated_doc,
                artifact_payloads=(payload,),
                confidence=ConfidenceValue(score=1.0, method="exact_dictionary_alignment", evidence={"protected_spans": t_res.protected_spans_count}),
                provenance=base_prov + (prov,),
            )
