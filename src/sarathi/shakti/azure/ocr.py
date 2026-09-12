"""Microsoft Azure Document Intelligence Cloud OCR Capability implementation for Sarathi.

Consumes documents, invokes Azure Document Intelligence prebuilt-layout,
and maps response into canonical PageData, TextSpan with exact confidence scores,
TableData, and TXT/DOCX artifacts.
"""

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
from sarathi.shakti.artifact_naming import infer_cloud_media_type as _infer_media_type
from sarathi.shakti.azure.client import AzureClient
from sarathi.shakti.azure.plugin import AZURE_OCR_DECLARATION
from sarathi.shakti.docx_exporter import build_docx_payload


def _parse_azure_tables(raw_tables: list[dict[str, Any]]) -> list[TableData]:
    """Parse Azure Document Intelligence table structures into canonical TableData."""
    canonical_tables: list[TableData] = []
    for t_idx, t_dict in enumerate(raw_tables, start=1):
        row_count = int(t_dict.get("rowCount", 0))
        col_count = int(t_dict.get("columnCount", 0))
        cells = t_dict.get("cells", [])
        if row_count < 2 or col_count < 1:
            continue

        grid = [["" for _ in range(col_count)] for _ in range(row_count)]
        for c in cells:
            r = int(c.get("rowIndex", 0))
            col = int(c.get("columnIndex", 0))
            if 0 <= r < row_count and 0 <= col < col_count:
                grid[r][col] = str(c.get("content", "")).strip()

        headers = tuple(grid[0])
        rows = tuple(tuple(row) for row in grid[1:])
        canonical_tables.append(
            TableData(
                name=f"azure_table_{t_idx}",
                headers=headers,
                rows=rows,
            )
        )
    return canonical_tables


class AzureOCRCapability:
    """Capability implementing Azure Document Intelligence Cloud OCR."""

    def __init__(
        self,
        client: AzureClient | None = None,
        declaration: CapabilityDeclaration = AZURE_OCR_DECLARATION,
        darpana: Any | None = None,
    ) -> None:
        self.declaration = declaration
        self._client = client or AzureClient()
        self._darpana = darpana

    def execute(
        self,
        request: Request,
        context: ExecutionContext,
        prior_result: Result | None = None,
    ) -> Result:
        """Execute Azure Document Intelligence OCR extraction on input documents."""
        if not isinstance(request, Request):
            raise TypeError(f"request must be a Request instance, got {type(request).__name__}.")
        if not isinstance(context, ExecutionContext):
            raise TypeError(f"context must be an ExecutionContext instance, got {type(context).__name__}.")

        if context.cancellation_token is not None and context.cancellation_token.is_cancelled:
            context.cancellation_token.check_cancelled()

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

            analyze_result = self._client.analyze_layout(
                content_bytes=content_bytes,
                media_type=media_type,
            )

            raw_pages = analyze_result.get("pages", [])
            raw_tables = analyze_result.get("tables", [])
            all_tables = _parse_azure_tables(raw_tables)

            pages: list[PageData] = []
            full_text_parts: list[str] = []

            for p_idx, p_dict in enumerate(raw_pages, start=1):
                page_lines = p_dict.get("lines", [])
                line_texts: list[str] = []
                spans: list[TextSpan] = []

                # Azure words contain exact confidence scores
                page_words = p_dict.get("words", [])
                word_confs = [
                    float(w["confidence"])
                    for w in page_words
                    if "confidence" in w and isinstance(w["confidence"], (int, float))
                ]

                for line in page_lines:
                    l_text = line.get("content", "").strip()
                    if l_text:
                        line_texts.append(l_text)

                p_text = "\n".join(line_texts) if line_texts else p_dict.get("content", "")
                full_text_parts.append(p_text)

                for w in page_words:
                    w_text = w.get("content", "")
                    w_conf = float(w["confidence"]) if "confidence" in w and isinstance(w["confidence"], (int, float)) else None
                    polygon = w.get("polygon", [])
                    bbox = None
                    if len(polygon) >= 8:
                        xs = [polygon[i] for i in range(0, len(polygon), 2)]
                        ys = [polygon[i] for i in range(1, len(polygon), 2)]
                        bbox = (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))
                    spans.append(
                        TextSpan(
                            text=w_text,
                            bounding_box=bbox,
                            confidence=w_conf,
                        )
                    )

                page_avg_conf = round(sum(word_confs) / len(word_confs), 4) if word_confs else None
                min_c = round(min(word_confs), 4) if word_confs else None
                max_c = round(max(word_confs), 4) if word_confs else None

                page_meta = {
                    "confidence": page_avg_conf,
                    "min_confidence": min_c,
                    "max_confidence": max_c,
                    "confidence_count": len(word_confs),
                }

                page_tables = [t for t in all_tables] if p_idx == 1 else []

                page_data = PageData(
                    page_number=p_idx,
                    text=p_text,
                    spans=tuple(spans),
                    tables=tuple(page_tables),
                    metadata=page_meta,
                )
                pages.append(page_data)

                # Emit Pramana telemetry if Darpana is wired
                if self._darpana is not None:
                    from datetime import datetime, timezone

                    from sarathi.darpana import PramanaRecord

                    now_iso = datetime.now(timezone.utc).isoformat()
                    page_evidence = {
                        "score_kind": "raw_engine",
                        "calibrated": False,
                        "provider": "azure",
                        "service": "document_intelligence",
                    }
                    self._darpana.record_pramana(
                        PramanaRecord(
                            run_id=context.run_id,
                            request_id=context.request_id,
                            trace_id=context.trace_id,
                            span_id=context.span_id,
                            capability_id="azure_ocr",
                            stage="ocr",
                            timestamp_utc=now_iso,
                            subject_id=f"{inp.input_id}:p{p_idx}",
                            confidence=ConfidenceValue(
                                score=page_avg_conf,
                                method="azure_word_mean",
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

            doc_text = analyze_result.get("content") or "\n\n".join(full_text_parts).strip()
            doc = CanonicalDocument(
                document_id=f"doc-azure-{inp.input_id}",
                source_input_id=inp.input_id,
                text=doc_text,
                pages=tuple(pages),
                metadata={"provider": "azure_document_intelligence"},
            )
            all_docs.append(doc)

            txt_name = format_artifact_filename(inp, "azure_ocr", "txt", all_inputs=request.inputs)
            docx_name = format_artifact_filename(inp, "azure_ocr", "docx", all_inputs=request.inputs)

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
                    header_text=f"Azure OCR - {inp.display_name}",
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
                method="azure_mean",
                evidence={
                    "provider": "azure",
                    "sample_count": len(all_confs),
                    "min_confidence": round(min(all_confs), 4),
                    "max_confidence": round(max(all_confs), 4),
                },
            )

        provenance = (
            ProvenanceRecord(
                capability_id="azure_ocr",
                evidence={"provider": "azure_document_intelligence"},
            ),
        )

        return Result(
            data=output_data,
            artifact_payloads=tuple(all_payloads),
            provenance=provenance,
            confidence=overall_confidence,
        )
