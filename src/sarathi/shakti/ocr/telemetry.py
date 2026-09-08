"""Fine-grained worker performance and page/region quality telemetry for OCR."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sarathi.darpana import MarutiRecord, PramanaRecord
from sarathi.sankalpa import ConfidenceValue, ExecutionContext, InputRef, PageData

if TYPE_CHECKING:
    from sarathi.darpana import Darpana


def record_ocr_page_telemetry(
    darpana: Darpana | None,
    context: ExecutionContext,
    inp_ref: InputRef,
    page_idx: int,
    page_data: PageData,
    dur_ns: int,
    binding: Any,
    worker_id: str,
) -> None:
    """Record fine-grained worker performance and page/region quality telemetry in Darpana."""
    if darpana is None:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    dev_t = binding.device_type.value.upper() if binding and hasattr(binding, "device_type") else "CPU"
    dev_i = str(getattr(binding, "device_id", "0")) if binding else "0"

    darpana.record_maruti(
        MarutiRecord(
            run_id=context.run_id,
            request_id=context.request_id,
            trace_id=context.trace_id,
            span_id=context.span_id,
            phase_name="worker_execution",
            component="shakti.ocr",
            timestamp_utc=now_iso,
            duration_ns=dur_ns,
            outcome="success",
            attributes={
                "worker_id": worker_id,
                "device_type": dev_t,
                "device_id": dev_i,
                "pages_processed": 1,
                "page_number": page_idx,
                "file_display_name": inp_ref.display_name,
            },
        )
    )

    span_confs = [s.confidence for s in page_data.spans if s.confidence is not None]
    p_conf = (sum(span_confs) / len(span_confs)) if span_confs else None
    min_c = min(span_confs) if span_confs else None
    max_c = max(span_confs) if span_confs else None

    page_attrs: dict[str, Any] = {
        "level": "page",
        "device_type": dev_t,
        "device_id": dev_i,
        "page_number": page_idx,
        "file_display_name": inp_ref.display_name,
        "region_count": len(page_data.spans),
        "min_confidence": min_c,
        "max_confidence": max_c,
        "review_recommended": (p_conf < 0.75) if p_conf is not None else False,
    }
    page_evidence: dict[str, Any] = {
        "score_kind": "raw_engine",
        "calibrated": False,
        "review_recommended": (p_conf < 0.75) if p_conf is not None else False,
    }
    if page_data.metadata and page_data.metadata.get("fallback_applied"):
        page_attrs["fallback_applied"] = True
        page_attrs["fallback_engine"] = page_data.metadata.get("fallback_engine", "tesseract5")
        page_attrs["fallback_improved_count"] = page_data.metadata.get("fallback_improved_count", 0)
        page_attrs["fallback_intercepted_count"] = page_data.metadata.get("fallback_intercepted_count", 0)
        fb_delta = page_data.metadata.get("raw_confidence_score_delta", page_data.metadata.get("fallback_total_gain", 0.0))
        page_attrs["raw_confidence_score_delta"] = fb_delta
        page_attrs["fallback_total_gain"] = fb_delta
        page_evidence["fallback_applied"] = True

    page_cv = (
        ConfidenceValue(
            score=round(p_conf, 4),
            method="rapidocr",
            evidence=page_evidence,
        )
        if p_conf is not None
        else None
    )

    darpana.record_pramana(
        PramanaRecord(
            run_id=context.run_id,
            request_id=context.request_id,
            trace_id=context.trace_id,
            span_id=context.span_id,
            capability_id="ocr",
            stage="ocr",
            timestamp_utc=now_iso,
            subject_id=f"{inp_ref.input_id}:p{page_idx}",
            confidence=page_cv,
            attributes=page_attrs,
        )
    )

    for s_idx, span in enumerate(page_data.spans[:30]):
        s_conf = span.confidence
        span_meta = span.metadata or {}
        is_fallback = bool(span_meta.get("fallback_applied", False))
        orig_c = span_meta.get("original_confidence")
        delta = span_meta.get("raw_confidence_score_delta", span_meta.get("confidence_gain"))
        reg_method = "tesseract_fallback" if is_fallback else "rapidocr_line"

        reg_attrs: dict[str, Any] = {
            "level": "region",
            "device_type": dev_t,
            "device_id": dev_i,
            "region_id": f"p{page_idx}_line_{s_idx + 1}",
            "page_number": page_idx,
            "file_display_name": inp_ref.display_name,
            "region_type": "line",
            "review_recommended": (s_conf < 0.75) if s_conf is not None else False,
        }
        reg_evidence: dict[str, Any] = {
            "score_kind": "raw_engine",
            "calibrated": False,
            "review_recommended": (s_conf < 0.75) if s_conf is not None else False,
        }
        if is_fallback:
            reg_attrs["fallback_applied"] = True
            reg_attrs["fallback_engine"] = span_meta.get("fallback_engine", "tesseract5")
            if orig_c is not None:
                reg_attrs["original_confidence"] = orig_c
                reg_evidence["original_confidence"] = orig_c
            if s_conf is not None:
                reg_attrs["replacement_confidence"] = s_conf
                reg_evidence["replacement_confidence"] = s_conf
            if delta is not None:
                reg_attrs["raw_confidence_score_delta"] = delta
                reg_attrs["confidence_gain"] = delta
                reg_evidence["raw_confidence_score_delta"] = delta
                reg_evidence["confidence_gain"] = delta
            reg_evidence["fallback_applied"] = True
            reg_evidence["fallback_engine"] = "tesseract5"

        span_cv = (
            ConfidenceValue(
                score=round(s_conf, 4),
                method=reg_method,
                evidence=reg_evidence,
            )
            if s_conf is not None
            else None
        )

        darpana.record_pramana(
            PramanaRecord(
                run_id=context.run_id,
                request_id=context.request_id,
                trace_id=context.trace_id,
                span_id=context.span_id,
                capability_id="ocr",
                stage="ocr",
                timestamp_utc=now_iso,
                subject_id=f"{inp_ref.input_id}:p{page_idx}:r{s_idx}",
                confidence=span_cv,
                attributes=reg_attrs,
            )
        )
