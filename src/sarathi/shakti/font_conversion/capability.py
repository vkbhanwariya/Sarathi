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
from sarathi.shakti.docx_exporter import build_docx_payload, transform_docx_artifact
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
        if all(
            not d.text.strip()
            and not d.tables
            and not any(p.text.strip() or p.tables for p in d.pages)
            for d in docs
        ):
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

                target_mode = (
                    request.custom_options.get("font_mode", "auto_unicode")
                    if request.custom_options
                    else "auto_unicode"
                )

                is_to_legacy = target_mode in ("to_krutidev", "to_devlys")
                target_profile = (
                    ("krutidev010" if target_mode == "to_krutidev" else "devlys010")
                    if is_to_legacy
                    else (detected_profile or "krutidev010")
                )

                if is_to_legacy:
                    # Preserve detected_profile for legacy-to-legacy decoding; conf reflects detection evidence
                    pass
                else:
                    # Default: auto_unicode
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

                total_spans_count = 0

                def _conv_text(raw: str) -> str:
                    nonlocal total_spans_count
                    prot, c_spans = self._protector.protect(raw, protect_devanagari=not is_to_legacy)
                    total_spans_count += len(c_spans)
                    if is_to_legacy:
                        if detected_profile is not None and detected_profile != target_profile:
                            inter = self._converter.convert(prot, profile_id=detected_profile)
                        else:
                            inter = prot
                        c_raw = self._converter.convert_to_legacy(inter, target_profile_id=target_profile)
                    else:
                        c_raw = self._converter.convert(prot, profile_id=detected_profile)
                    restored = self._protector.restore(c_raw, c_spans)
                    if not is_to_legacy:
                        if not self._validator.validate_protection_integrity(restored, c_spans):
                            raise DoshError(
                                code=FailureCode.EXECUTION_FAILED,
                                message="Protected span integrity validation failed during font conversion.",
                            )
                    return restored

                final_text = _conv_text(full_text)

                # Convert tables if present
                converted_tables: list[TableData] = []
                for t in doc.tables:
                    t_rows: list[tuple[str, ...]] = []
                    for row in t.rows:
                        t_rows.append(tuple(_conv_text(str(cell)) for cell in row))
                    t_headers = tuple(_conv_text(str(h)) for h in t.headers) if t.headers else ()
                    converted_tables.append(
                        TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata)
                    )

                # Convert pages if present
                converted_pages: list[PageData] = []
                for p in doc.pages:
                    p_conv = _conv_text(p.text)
                    p_page_tables: list[TableData] = []
                    for t in p.tables:
                        t_rows = [tuple(_conv_text(str(cell)) for cell in row) for row in t.rows]
                        t_headers = tuple(_conv_text(str(h)) for h in t.headers) if t.headers else ()
                        p_page_tables.append(
                            TableData(name=t.name, headers=t_headers, rows=tuple(t_rows), metadata=t.metadata)
                        )
                    converted_pages.append(
                        PageData(
                            page_number=p.page_number,
                            text=p_conv,
                            spans=p.spans,
                            tables=tuple(p_page_tables),
                            metadata=p.metadata,
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
                    evidence={
                        "profile_id": detected_profile,
                        "confidence": conf,
                        "protected_spans_count": total_spans_count,
                    },
                )
                all_provs.append(prov)

                txt_artifact_name = (
                    "Converted_Document.txt"
                    if len(docs) == 1
                    else f"Converted_{doc.source_input_id or doc.document_id}.txt"
                )
                payloads.append(
                    ArtifactPayload(
                        intent=ArtifactIntent(name=txt_artifact_name, role="converted_text", media_type="text/plain"),
                        content=final_text.encode("utf-8"),
                    )
                )

                docx_artifact_name = (
                    "Converted_Document.docx"
                    if len(docs) == 1
                    else f"Converted_{doc.source_input_id or doc.document_id}.docx"
                )

                # Attempt in-place transformation if original source file is a valid DOCX
                docx_payload: ArtifactPayload | None = None
                matching_inp = next((i for i in request.inputs if i.input_id == doc.source_input_id), None)
                if matching_inp is None and idx < len(request.inputs):
                    matching_inp = request.inputs[idx]

                if (
                    matching_inp is not None
                    and matching_inp.source_path is not None
                    and matching_inp.source_path.suffix.lower() == ".docx"
                    and matching_inp.source_path.is_file()
                ):
                    try:
                        raw_docx_bytes = matching_inp.source_path.read_bytes()
                        docx_payload = transform_docx_artifact(
                            input_bytes=raw_docx_bytes,
                            converter_fn=_conv_text,
                            filename=docx_artifact_name,
                            role="converted_document",
                        )
                    except Exception:
                        docx_payload = None

                if docx_payload is None:
                    docx_payload = build_docx_payload(
                        doc=converted_doc,
                        filename=docx_artifact_name,
                        role="converted_document",
                    )
                payloads.append(docx_payload)

        final_data = tuple(converted_docs) if is_batch else converted_docs[0]
        return Result(
            data=final_data,
            artifact_payloads=tuple(payloads),
            provenance=tuple(all_provs),
            warnings=tuple(all_warnings),
        )
