"""Roopa Font Conversion Executable Capability for Sarathi V2."""

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
from sarathi.shakti.font_conversion.converter import FontConverter
from sarathi.shakti.font_conversion.detector import LegacyFontDetector
from sarathi.shakti.font_conversion.plugin import CAPABILITY_DECLARATION
from sarathi.shakti.font_conversion.protector import TextProtector
from sarathi.shakti.font_conversion.validator import FontConversionValidator

_CANONICAL_FONTS_DIR = Path(__file__).resolve().parents[4] / "data" / "fonts"


class FontConversionCapability:
    """Executable capability for legacy font to Unicode conversion."""

    def __init__(
        self,
        darpana: Darpana | None = None,
        fonts_dir: Path | None = None,
        anubhava_path: Path | None = None,
    ) -> None:
        self.declaration = CAPABILITY_DECLARATION
        self._darpana = darpana
        self._fonts_dir = fonts_dir.resolve() if fonts_dir is not None else _CANONICAL_FONTS_DIR
        self._detector = LegacyFontDetector(fonts_dir=self._fonts_dir)
        self._protector = TextProtector()
        self._converter = FontConverter(fonts_dir=self._fonts_dir, anubhava_path=anubhava_path)
        self._validator = FontConversionValidator()

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute font conversion on the request inputs or prior CanonicalDocument(s)."""
        if prior_result is None or prior_result.data is None:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="FontConversionCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )

        docs: list[CanonicalDocument]
        is_batch = False
        if isinstance(prior_result.data, CanonicalDocument):
            docs = [prior_result.data]
        elif isinstance(prior_result.data, (tuple, list)) and all(
            isinstance(d, CanonicalDocument) for d in prior_result.data
        ):
            docs = list(prior_result.data)
            is_batch = True
        else:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="FontConversionCapability requires a prior Result containing a CanonicalDocument or tuple of documents.",
            )

        if not docs:
            raise DoshError(
                code=FailureCode.VALIDATION_FAILED,
                message="No CanonicalDocument provided to FontConversionCapability.",
            )

        # If document text, pages, and tables are completely empty, request OCR continuation through Pravaha
        if all(not d.text.strip() and not any(p.tables for p in d.pages) and not d.tables and d.pages for d in docs):
            return Result(data=prior_result.data, next_requirement="ocr", resume_self=True)

        converted_docs: list[CanonicalDocument] = []
        payloads: list[ArtifactPayload] = []
        all_provs: list[ProvenanceRecord] = list(prior_result.provenance)
        all_warnings: list[WarningRecord] = []

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

            scope = (
                self._darpana.time_scope(
                    context=context, phase_name="font_conversion", component="shakti.font_conversion"
                )
                if self._darpana
                else nullcontext()
            )
            with scope:
                # 1. Detect legacy font profile
                font_hint = request.metadata.get("font") if request.metadata else None
                detected_profile, conf = self._detector.detect(
                    full_text, font_hint=str(font_hint) if font_hint else None
                )

                if detected_profile is None:
                    # No legacy font detected; keep original document
                    converted_docs.append(doc)
                    all_warnings.append(
                        WarningRecord(
                            code="NO_LEGACY_FONT_DETECTED",
                            message=f"No legacy font encoding detected in document '{doc.document_id}'.",
                            stage="font_conversion",
                        )
                    )
                    continue

                # 2. Protect non-legacy spans
                protected_text, spans = self._protector.protect(full_text)

                # 3. Convert legacy text to Unicode
                converted_raw = self._converter.convert(protected_text, profile_id=detected_profile)

                # 4. Restore protected spans
                final_text = self._protector.restore(converted_raw, spans)

                # 5. Validate protection integrity
                is_valid = self._validator.validate_protection_integrity(final_text, spans)
                if not is_valid:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Protected span integrity validation failed during font conversion.",
                    )

                # Convert tables if present
                converted_tables: list[TableData] = []
                for t in doc.tables:
                    t_rows: list[tuple[str, ...]] = []
                    for row in t.rows:
                        r_cells: list[str] = []
                        for cell in row:
                            c_prot, c_spans = self._protector.protect(str(cell))
                            c_conv = self._protector.restore(
                                self._converter.convert(c_prot, profile_id=detected_profile), c_spans
                            )
                            r_cells.append(c_conv)
                        t_rows.append(tuple(r_cells))
                    t_headers = (
                        tuple(
                            self._protector.restore(
                                self._converter.convert(h_prot, profile_id=detected_profile), h_spans
                            )
                            for h in t.headers
                            for h_prot, h_spans in [self._protector.protect(str(h))]
                        )
                        if t.headers
                        else ()
                    )
                    converted_tables.append(
                        TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata)
                    )

                # Convert pages if present
                converted_pages: list[PageData] = []
                for p in doc.pages:
                    p_text_prot, p_spans = self._protector.protect(p.text)
                    p_conv = self._protector.restore(
                        self._converter.convert(p_text_prot, profile_id=detected_profile), p_spans
                    )

                    p_page_tables: list[TableData] = []
                    for t in p.tables:
                        t_rows = []
                        for row in t.rows:
                            r_cells = []
                            for cell in row:
                                c_prot, c_spans = self._protector.protect(str(cell))
                                c_conv = self._protector.restore(
                                    self._converter.convert(c_prot, profile_id=detected_profile), c_spans
                                )
                                r_cells.append(c_conv)
                            t_rows.append(tuple(r_cells))
                        t_headers = (
                            tuple(
                                self._protector.restore(
                                    self._converter.convert(h_prot, profile_id=detected_profile), h_spans
                                )
                                for h in t.headers
                                for h_prot, h_spans in [self._protector.protect(str(h))]
                            )
                            if t.headers
                            else ()
                        )
                        p_page_tables.append(
                            TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata)
                        )
                    converted_pages.append(
                        PageData(
                            page_number=p.page_number, text=p_conv, tables=tuple(p_page_tables), metadata=p.metadata
                        )
                    )

                converted_doc = CanonicalDocument(
                    document_id=doc.document_id,
                    source_input_id=doc.source_input_id,
                    text=final_text,
                    pages=tuple(converted_pages),
                    tables=tuple(converted_tables or (converted_pages[0].tables if converted_pages else ())),
                    detected_type="unicode_document",
                    metadata=doc.metadata,
                )
                converted_docs.append(converted_doc)

                prov = ProvenanceRecord(
                    source_input_id=doc.source_input_id,
                    capability_id="font_conversion",
                    stage="font_conversion",
                    evidence={"profile_id": detected_profile, "confidence": conf, "protected_spans_count": len(spans)},
                )
                all_provs.append(prov)

                artifact_name = (
                    "Converted_Document.txt"
                    if len(docs) == 1
                    else f"Converted_{doc.source_input_id or doc.document_id}.txt"
                )
                payloads.append(
                    ArtifactPayload(
                        intent=ArtifactIntent(name=artifact_name, role="converted_text", media_type="text/plain"),
                        content=final_text.encode("utf-8"),
                    )
                )

        final_data = tuple(converted_docs) if is_batch else converted_docs[0]
        return Result(
            data=final_data,
            artifact_payloads=tuple(payloads),
            provenance=tuple(all_provs),
            warnings=tuple(all_warnings),
        )
