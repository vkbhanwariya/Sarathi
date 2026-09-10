"""Bhashini (Chitrakshar) Cloud OCR Capability implementation for Sarathi."""

from __future__ import annotations

from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ArtifactIntent,
    ArtifactPayload,
    CanonicalDocument,
    CapabilityDeclaration,
    ConfidenceValue,
    ExecutionContext,
    PageData,
    ProvenanceRecord,
    Request,
    Result,
    TableData,
    TextSpan,
)
from sarathi.shakti.artifact_naming import format_artifact_filename
from sarathi.shakti.bhashini.client import BhashiniClient
from sarathi.shakti.bhashini.plugin import BHASHINI_OCR_DECLARATION
from sarathi.shakti.docx_exporter import build_docx_payload


def _extract_markdown_tables(text: str) -> list[TableData]:
    """Scan text for markdown tables and parse them into TableData objects."""
    tables: list[TableData] = []
    lines = [line.strip() for line in text.splitlines()]

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2:
            table_lines = [line]
            i += 1
            while i < len(lines) and lines[i].startswith("|") and lines[i].endswith("|"):
                table_lines.append(lines[i])
                i += 1

            if len(table_lines) >= 2:
                headers = tuple(col.strip() for col in table_lines[0].strip("|").split("|"))
                data_start = 1
                if len(table_lines) > 1 and all(c in "-:| " for c in table_lines[1]):
                    data_start = 2

                rows: list[tuple[str, ...]] = []
                for r_line in table_lines[data_start:]:
                    rows.append(tuple(col.strip() for col in r_line.strip("|").split("|")))

                if headers and rows:
                    tables.append(TableData(name=f"table_{len(tables)+1}", headers=headers, rows=tuple(rows)))
        else:
            i += 1

    return tables


class BhashiniOCRCapability:
    """Capability implementing Bhashini Chitrakshar OCR."""

    def __init__(
        self,
        client: BhashiniClient | None = None,
        declaration: CapabilityDeclaration = BHASHINI_OCR_DECLARATION,
        darpana: Any | None = None,
    ) -> None:
        self.declaration = declaration
        self._client = client or BhashiniClient()
        self._darpana = darpana

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Bhashini OCR extraction on input documents."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        source_lang = "hi"
        if request.metadata and "source_lang" in request.metadata:
            source_lang = str(request.metadata["source_lang"])

        all_docs: list[CanonicalDocument] = []
        all_payloads: list[ArtifactPayload] = []

        for inp in request.inputs:
            if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
                context.cancellation_token.check_cancelled()

            try:
                content_bytes = inp.source_path.read_bytes()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message=f"Failed to read input file: {inp.display_name}",
                ) from exc

            response_json = self._client.process_ocr(
                content_bytes=content_bytes,
                source_lang=source_lang,
            )

            extracted_text = ""
            pipeline_resp = response_json.get("pipelineResponse", [])
            confidence_score: float | None = None

            if pipeline_resp:
                out_list = pipeline_resp[0].get("output", [])
                if out_list:
                    extracted_text = out_list[0].get("target") or out_list[0].get("source") or ""
                    if "confidence" in out_list[0]:
                        try:
                            confidence_score = float(out_list[0]["confidence"])
                        except (ValueError, TypeError):
                            pass

            paragraphs = [p.strip() for p in extracted_text.split("\n\n") if p.strip()]
            spans: list[TextSpan] = [
                TextSpan(text=p, confidence=confidence_score)
                for p in paragraphs
            ]

            tables = _extract_markdown_tables(extracted_text)

            page_meta: dict[str, Any] = {
                "confidence": confidence_score,
                "min_confidence": confidence_score,
                "max_confidence": confidence_score,
                "confidence_count": len(spans) if confidence_score is not None else 0,
            }

            page_data = PageData(
                page_number=1,
                text=extracted_text,
                spans=tuple(spans),
                tables=tuple(tables),
                metadata=page_meta,
            )

            if self._darpana is not None:
                from datetime import datetime, timezone

                from sarathi.darpana import PramanaRecord

                now_iso = datetime.now(timezone.utc).isoformat()
                page_evidence = {
                    "score_kind": "raw_engine",
                    "calibrated": False,
                    "provider": "bhashini",
                    "engine": "chitrakshar",
                }
                self._darpana.record_pramana(
                    PramanaRecord(
                        run_id=context.run_id,
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        span_id=context.span_id,
                        capability_id="bhashini_ocr",
                        stage="ocr",
                        timestamp_utc=now_iso,
                        subject_id=f"{inp.input_id}:p1",
                        confidence=ConfidenceValue(
                            score=confidence_score,
                            method="bhashini_confidence",
                            evidence=page_evidence,
                        ) if confidence_score is not None else None,
                        attributes={
                            "level": "page",
                            "page_number": 1,
                            "file_display_name": inp.display_name,
                            "region_count": len(spans),
                            "min_confidence": confidence_score,
                            "max_confidence": confidence_score,
                        },
                    )
                )

            doc = CanonicalDocument(
                document_id=f"doc-bhashini-{inp.input_id}",
                source_input_id=inp.input_id,
                text=extracted_text,
                pages=(page_data,),
                metadata={"provider": "bhashini_nltm"},
            )
            all_docs.append(doc)

            txt_name = format_artifact_filename(inp, "bhashini_ocr", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(inp, "bhashini_ocr", "docx", all_inputs=request.inputs)

            all_payloads.append(
                ArtifactPayload(
                    intent=ArtifactIntent(name=txt_name, role="ocr_text", media_type="text/plain"),
                    content=extracted_text.encode("utf-8"),
                )
            )
            all_payloads.append(
                build_docx_payload(
                    doc=doc,
                    filename=docx_name,
                    role="ocr_document",
                    header_text=f"Bhashini OCR - {inp.display_name}",
                )
            )

        output_data = all_docs[0] if len(all_docs) == 1 else tuple(all_docs)

        all_confs = [
            s.confidence
            for doc in all_docs
            for p in doc.pages
            for s in p.spans
            if s.confidence is not None
        ]
        overall_confidence: ConfidenceValue | None = None
        if all_confs:
            overall_confidence = ConfidenceValue(
                score=round(sum(all_confs) / len(all_confs), 4),
                method="bhashini_mean",
                evidence={
                    "score_kind": "raw_engine",
                    "calibrated": False,
                    "provider": "bhashini",
                    "engine": "chitrakshar",
                    "sample_count": len(all_docs),
                },
            )

        provenance = (
            ProvenanceRecord(
                capability_id="bhashini_ocr",
                evidence={"provider": "bhashini_nltm"},
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
            confidence=overall_confidence,
        )
