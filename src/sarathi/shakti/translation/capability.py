"""Executable Translation Capability for Sarathi V2."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from sarathi.darpana import Darpana
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
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.translation.detector import LanguageDetector
from sarathi.shakti.translation.engine import (
    CTranslate2TranslationEngine,
    TranslatorBackend,
)
from sarathi.shakti.translation.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.translation.protector import TranslationProtector


class TranslationCapability:
    """Canonical executable capability for bilingual document translation."""

    def __init__(
        self,
        darpana: Darpana | None = None,
        data_root: Path | None = None,
        backend: TranslatorBackend | None = None,
    ) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._detector = LanguageDetector()
        self._protector = TranslationProtector()
        self._engine = CTranslate2TranslationEngine(
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

        # If document text, pages, and tables are completely empty, request OCR continuation through Pravaha
        if all(
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
                # 1. Translate main document text
                t_res = self._engine.translate(full_text, direction=direction)

                # 2. Translate table data if present
                converted_tables: list[TableData] = []
                for t in doc.tables:
                    t_rows: list[tuple[str, ...]] = []
                    for row in t.rows:
                        r_cells = [
                            self._engine.translate(str(cell), direction=direction).translated_text for cell in row
                        ]
                        t_rows.append(tuple(r_cells))
                    t_headers = (
                        tuple(self._engine.translate(str(h), direction=direction).translated_text for h in t.headers)
                        if t.headers
                        else ()
                    )
                    converted_tables.append(
                        TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata)
                    )

                # 3. Translate page text if present (preserving spans)
                converted_pages: list[PageData] = []
                for p in doc.pages:
                    p_res = self._engine.translate(p.text, direction=direction)
                    p_tables: list[TableData] = []
                    for t in p.tables:
                        t_rows = [
                            tuple(self._engine.translate(str(cell), direction=direction).translated_text for cell in row)
                            for row in t.rows
                        ]
                        t_headers = (
                            tuple(self._engine.translate(str(h), direction=direction).translated_text for h in t.headers)
                            if t.headers
                            else ()
                        )
                        p_tables.append(TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata))
                    converted_pages.append(
                        PageData(
                            page_number=p.page_number,
                            text=p_res.translated_text,
                            spans=p.spans,
                            tables=tuple(p_tables),
                            metadata=p.metadata,
                        )
                    )

                translated_doc = CanonicalDocument(
                    document_id=doc.document_id,
                    source_input_id=doc.source_input_id,
                    text=t_res.translated_text,
                    pages=tuple(converted_pages),
                    tables=tuple(converted_tables or (converted_pages[0].tables if converted_pages else ())),
                    detected_type="translated_document",
                    metadata=doc.metadata,
                )
                translated_docs.append(translated_doc)

                prov = ProvenanceRecord(
                    source_input_id=doc.source_input_id,
                    capability_id="translation",
                    stage="translation",
                    evidence={
                        "direction": direction.value,
                        "source_language": t_res.source_language.value,
                        "target_language": t_res.target_language.value,
                        "protected_spans_count": t_res.protected_spans_count,
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
                    content=t_res.translated_text.encode("utf-8"),
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
        )
