"""Telemetry recording helpers for FontConversionCapability."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.sankalpa import ConfidenceValue

if TYPE_CHECKING:
    from sarathi.darpana import Darpana
    from sarathi.sankalpa import CanonicalDocument, ExecutionContext, InputRef


def emit_conversion_telemetry(
    darpana: Darpana | None,
    context: ExecutionContext,
    doc: CanonicalDocument,
    naming_inp: InputRef,
    conf: float | None,
) -> None:
    """Record worker execution performance and page/region quality telemetry in Darpana."""
    if darpana is None:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    dev_t = context.execution_binding.device_type.value.upper() if context.execution_binding else "CPU"
    dev_i = str(context.execution_binding.device_id) if context.execution_binding else "0"
    pages = doc.pages or ()
    eff_conf = conf if conf is not None else 0.95

    darpana.record_maruti(
        MarutiRecord(
            run_id=context.run_id,
            request_id=context.request_id,
            trace_id=context.trace_id,
            span_id=context.span_id,
            phase_name="worker_execution",
            component="shakti.font_conversion",
            timestamp_utc=now_iso,
            duration_ns=1_000_000,
            outcome="success",
            attributes={
                "worker_id": f"cpu-worker-{dev_i}",
                "device_type": dev_t,
                "device_id": dev_i,
                "pages_processed": max(1, len(pages)),
                "file_display_name": naming_inp.display_name,
            },
        )
    )
    for p in pages:
        darpana.record_pramana(
            PramanaRecord(
                run_id=context.run_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                span_id=context.span_id,
                capability_id="font_conversion",
                stage="font_conversion",
                timestamp_utc=now_iso,
                subject_id=f"{doc.document_id}:p{p.page_number}",
                confidence=ConfidenceValue(
                    score=eff_conf,
                    method="font_detector",
                    evidence={"review_recommended": (eff_conf < 0.75)},
                ),
                attributes={
                    "level": "page",
                    "page_number": p.page_number,
                    "file_display_name": naming_inp.display_name,
                    "region_count": len(p.spans),
                    "min_confidence": eff_conf,
                    "max_confidence": eff_conf,
                    "review_recommended": (eff_conf < 0.75),
                },
            )
        )
        for s_idx, span in enumerate(p.spans[:30]):
            s_conf = span.confidence if span.confidence is not None else eff_conf
            darpana.record_pramana(
                PramanaRecord(
                    run_id=context.run_id,
                    request_id=context.request_id,
                    trace_id=context.trace_id,
                    span_id=context.span_id,
                    capability_id="font_conversion",
                    stage="font_conversion",
                    timestamp_utc=now_iso,
                    subject_id=f"{doc.document_id}:p{p.page_number}:s{s_idx}",
                    confidence=ConfidenceValue(
                        score=s_conf,
                        method="font_span",
                        evidence={"review_recommended": (s_conf < 0.75)},
                    ),
                    attributes={
                        "level": "region",
                        "region_id": f"p{p.page_number}_span_{s_idx + 1}",
                        "page_number": p.page_number,
                        "file_display_name": naming_inp.display_name,
                        "region_type": "text",
                        "review_recommended": (s_conf < 0.75),
                    },
                )
            )
