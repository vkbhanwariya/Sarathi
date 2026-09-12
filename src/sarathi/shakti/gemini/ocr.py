"""Google Gemini Cloud OCR Capability implementation for Sarathi.

Consumes document images/PDFs, invokes Gemini multimodal API via GeminiClient,
and maps response into canonical PageData, TableData, and TXT/DOCX artifacts
with a standardized confidence matrix.
"""

from __future__ import annotations

import math
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
    TextSpan,
)
from sarathi.shakti.artifact_naming import format_artifact_filename
from sarathi.shakti.artifact_naming import infer_cloud_media_type as _infer_media_type
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.gemini.client import GeminiClient
from sarathi.shakti.gemini.plugin import GEMINI_OCR_DECLARATION
from sarathi.shakti.text.markdown import extract_markdown_tables


class GeminiOCRCapability:
    """Capability implementing Google Gemini Multimodal Cloud OCR."""

    def __init__(
        self,
        client: GeminiClient | None = None,
        declaration: CapabilityDeclaration = GEMINI_OCR_DECLARATION,
        darpana: Any | None = None,
    ) -> None:
        self.declaration = declaration
        self._client = client or GeminiClient()
        self._darpana = darpana

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Gemini OCR extraction on input documents."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        model = (
            request.custom_options.get("model", "gemini-2.5-flash")
            if request.custom_options
            else "gemini-2.5-flash"
        )

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

            media_type = inp.media_type or _infer_media_type(inp.source_path)

            response_json = self._client.process_ocr(
                content_bytes=content_bytes,
                media_type=media_type,
                model=model,
            )

            candidates = response_json.get("candidates", [])
            extracted_text = ""
            confidence_score: float | None = None

            if candidates:
                cand = candidates[0]
                content = cand.get("content", {})
                parts = content.get("parts", [])
                extracted_text = "".join(p.get("text", "") for p in parts).strip()

                # Derive confidence if avgLogprobs is available from Gemini
                avg_logprob = cand.get("avgLogprobs")
                if isinstance(avg_logprob, (int, float)) and avg_logprob <= 0.0:
                    confidence_score = round(max(0.1, min(1.0, math.exp(float(avg_logprob)))), 4)

            # Split into paragraph spans
            paragraphs = [p.strip() for p in extracted_text.split("\n\n") if p.strip()]
            spans: list[TextSpan] = [
                TextSpan(text=p, confidence=confidence_score)
                for p in paragraphs
            ]

            tables = extract_markdown_tables(extracted_text)

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

            # Telemetry to Darpana
            if self._darpana is not None:
                from datetime import datetime, timezone

                from sarathi.darpana import PramanaRecord

                now_iso = datetime.now(timezone.utc).isoformat()
                page_evidence = {
                    "score_kind": "raw_engine",
                    "calibrated": False,
                    "model": model,
                    "provider": "gemini",
                }
                self._darpana.record_pramana(
                    PramanaRecord(
                        run_id=context.run_id,
                        request_id=context.request_id,
                        trace_id=context.trace_id,
                        span_id=context.span_id,
                        capability_id="gemini_ocr",
                        stage="ocr",
                        timestamp_utc=now_iso,
                        subject_id=f"{inp.input_id}:p1",
                        confidence=ConfidenceValue(
                            score=confidence_score,
                            method="gemini_logprob",
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
                document_id=f"doc-gemini-{inp.input_id}",
                source_input_id=inp.input_id,
                text=extracted_text,
                pages=(page_data,),
                metadata={"model": model, "provider": "google_gemini"},
            )
            all_docs.append(doc)

            txt_name = format_artifact_filename(inp, "gemini_ocr", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(inp, "gemini_ocr", "docx", all_inputs=request.inputs)

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
                    header_text=f"Gemini OCR - {inp.display_name}",
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
                method="gemini_mean",
                evidence={
                    "model": model,
                    "provider": "google_gemini",
                    "sample_count": len(all_confs),
                    "min_confidence": round(min(all_confs), 4),
                    "max_confidence": round(max(all_confs), 4),
                },
            )

        provenance = (
            ProvenanceRecord(
                capability_id="gemini_ocr",
                evidence={"model": model, "provider": "google_gemini"},
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
            confidence=overall_confidence,
        )
