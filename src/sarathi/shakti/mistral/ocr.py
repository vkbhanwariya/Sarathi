"""Mistral Cloud OCR Capability implementation for Sarathi.

Consumes documents/images, invokes mistral-ocr-latest via MistralClient,
and maps response into canonical PageData, TextSpan bounding boxes, TableData,
and TXT/DOCX artifacts.
"""

from __future__ import annotations

from pathlib import Path
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
from sarathi.shakti.docx_exporter import build_docx_payload
from sarathi.shakti.mistral.client import MistralClient
from sarathi.shakti.mistral.plugin import MISTRAL_OCR_DECLARATION


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


def _infer_media_type(path: Path) -> str:
    """Infer media type from file extension."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    return "application/octet-stream"


class MistralOCRCapability:
    """Capability implementing Mistral Cloud OCR (mistral-ocr-latest)."""

    def __init__(
        self,
        client: MistralClient | None = None,
        declaration: CapabilityDeclaration = MISTRAL_OCR_DECLARATION,
        darpana: Any | None = None,
    ) -> None:
        self.declaration = declaration
        self._client = client or MistralClient()
        self._darpana = darpana

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Mistral OCR extraction on input documents."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

        model = (
            request.custom_options.get("model", "mistral-ocr-latest")
            if request.custom_options
            else "mistral-ocr-latest"
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

            # Invoke Mistral OCR API
            response_json = self._client.process_ocr(
                content_bytes=content_bytes,
                media_type=media_type,
                model=model,
                include_blocks=True,
            )

            raw_pages = response_json.get("pages", [])
            pages: list[PageData] = []
            full_text_parts: list[str] = []

            for p_idx, p_dict in enumerate(raw_pages, start=1):
                p_text = p_dict.get("markdown", "") or p_dict.get("text", "")
                full_text_parts.append(p_text)

                spans: list[TextSpan] = []
                tables: list[TableData] = []

                # Extract block level bounding boxes if returned by Mistral OCR
                blocks = p_dict.get("blocks", [])
                for block in blocks:
                    b_text = block.get("text", "")
                    b_box = block.get("bbox")
                    b_conf = block.get("confidence")
                    if b_box and len(b_box) == 4:
                        spans.append(
                            TextSpan(
                                text=b_text,
                                bounding_box=(
                                    float(b_box[0]),
                                    float(b_box[1]),
                                    float(b_box[2]),
                                    float(b_box[3]),
                                ),
                                confidence=float(b_conf) if b_conf is not None else None,
                            )
                        )

                # Attempt to extract tables from page markdown
                tables = _extract_markdown_tables(p_text)

                # Compute page-level confidence matrix from spans
                span_confs = [s.confidence for s in spans if s.confidence is not None]
                page_meta: dict[str, Any] = {}
                page_avg_conf: float | None = round(sum(span_confs) / len(span_confs), 4) if span_confs else None
                min_c: float | None = round(min(span_confs), 4) if span_confs else None
                max_c: float | None = round(max(span_confs), 4) if span_confs else None

                if page_avg_conf is not None:
                    page_meta["confidence"] = page_avg_conf
                    page_meta["min_confidence"] = min_c
                    page_meta["max_confidence"] = max_c
                    page_meta["confidence_count"] = len(span_confs)

                page_data = PageData(
                    page_number=p_idx,
                    text=p_text,
                    spans=tuple(spans),
                    tables=tuple(tables),
                    metadata=page_meta,
                )
                pages.append(page_data)

                # Emit Pramana telemetry if Darpana is wired
                if self._darpana is not None:
                    from datetime import datetime, timezone

                    from sarathi.darpana import PramanaRecord

                    now_iso = datetime.now(timezone.utc).isoformat()
                    page_evidence = {"model": model, "provider": "mistral"}
                    self._darpana.record_pramana(
                        PramanaRecord(
                            run_id=context.run_id,
                            request_id=context.request_id,
                            trace_id=context.trace_id,
                            span_id=context.span_id,
                            capability_id="mistral_ocr",
                            stage="ocr",
                            timestamp_utc=now_iso,
                            subject_id=f"{inp.input_id}:p{p_idx}",
                            confidence=ConfidenceValue(
                                score=page_avg_conf,
                                method="mistral_mean",
                                evidence=page_evidence,
                            ) if page_avg_conf is not None else None,
                            attributes={
                                "level": "page",
                                "page_number": p_idx,
                                "file_display_name": inp.display_name,
                                "region_count": len(spans),
                                "min_confidence": min_c,
                                "max_confidence": max_c,
                            },
                        )
                    )
                    for s_idx, span in enumerate(spans[:30]):
                        if span.confidence is not None:
                            self._darpana.record_pramana(
                                PramanaRecord(
                                    run_id=context.run_id,
                                    request_id=context.request_id,
                                    trace_id=context.trace_id,
                                    span_id=context.span_id,
                                    capability_id="mistral_ocr",
                                    stage="ocr",
                                    timestamp_utc=now_iso,
                                    subject_id=f"{inp.input_id}:p{p_idx}:s{s_idx}",
                                    confidence=ConfidenceValue(
                                        score=round(span.confidence, 4),
                                        method="mistral_block",
                                        evidence=page_evidence,
                                    ),
                                    attributes={
                                        "level": "region",
                                        "page_number": p_idx,
                                        "region_index": s_idx,
                                        "confidence_score": round(span.confidence, 4),
                                    },
                                )
                            )

            doc_text = "\n\n".join(full_text_parts).strip()
            doc = CanonicalDocument(
                document_id=f"doc-mistral-{inp.input_id}",
                source_input_id=inp.input_id,
                text=doc_text,
                pages=tuple(pages),
                metadata={"model": model, "provider": "mistral"},
            )
            all_docs.append(doc)

            # Generate canonical TXT and DOCX artifact payloads
            txt_name = format_artifact_filename(inp, "mistral_ocr", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(inp, "mistral_ocr", "docx", all_inputs=request.inputs)

            all_payloads.append(
                ArtifactPayload(
                    intent=ArtifactIntent(name=txt_name, role="ocr_text", media_type="text/plain"),
                    content=doc_text.encode("utf-8"),
                )
            )
            all_payloads.append(
                build_docx_payload(
                    doc=doc,
                    filename=docx_name,
                    role="ocr_document",
                    header_text=f"OCR - {inp.display_name}",
                )
            )

        output_data = all_docs[0] if len(all_docs) == 1 else tuple(all_docs)

        # Aggregate overall measured confidence across all pages
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
                method="mistral_mean",
                evidence={
                    "model": model,
                    "provider": "mistral",
                    "sample_count": len(all_confs),
                    "min_confidence": round(min(all_confs), 4),
                    "max_confidence": round(max(all_confs), 4),
                },
            )

        provenance = (
            ProvenanceRecord(
                capability_id="mistral_ocr",
                evidence={"model": model, "provider": "mistral"},
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
            confidence=overall_confidence,
        )
