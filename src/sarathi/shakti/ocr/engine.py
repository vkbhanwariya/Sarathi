"""RapidOCR + OpenVINO Primary Engine Adapter for OCR Phase 1."""

from __future__ import annotations

import io
import sys
from typing import Any
import unicodedata

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ConfidenceValue,
    PageData,
    ProvenanceRecord,
    TextSpan,
    WarningRecord,
)

_ENGINE_INSTANCE: Any = None
_STAGE_NAME = "ocr"
_PLUGIN_ID = "shakti.ocr"
_CAPABILITY_ID = "ocr"


def _get_rapidocr_engine() -> Any:
    """Lazily load and return the RapidOCR OpenVINO engine instance."""
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        try:
            import openvino

            if "openvino.runtime" not in sys.modules:
                sys.modules["openvino.runtime"] = openvino

            from rapidocr_openvino import RapidOCR

            _ENGINE_INSTANCE = RapidOCR()
        except ImportError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="OCR dependencies are not installed. Install with 'uv add --optional ocr'.",
            ) from exc
    return _ENGINE_INSTANCE


def extract_images_from_bytes(data: bytes) -> list[Any]:
    """Convert input file bytes (PDF or Image) into a list of PIL RGB images."""
    from PIL import Image, UnidentifiedImageError

    # 1. Check if PDF
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            import pymupdf

            doc = pymupdf.open(stream=data, filetype="pdf")
            images = []
            try:
                for page in doc:
                    pix = page.get_pixmap(dpi=150)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    images.append(img)
            finally:
                doc.close()
            return images
        except Exception:
            return []

    # 2. Check if standard Image format
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        return [img]
    except (UnidentifiedImageError, OSError, ValueError):
        return []


def ocr_page_image(
    image: Any,
    page_number: int,
    input_id: str,
) -> tuple[PageData, ProvenanceRecord, ConfidenceValue | None]:
    """Run RapidOCR on a single PIL RGB image and return PageData, Provenance, and Confidence."""
    import numpy as np

    engine = _get_rapidocr_engine()
    img_arr = np.array(image)

    ocr_results, _ = engine(img_arr)

    spans: list[TextSpan] = []
    lines: list[str] = []
    conf_scores: list[float] = []

    if ocr_results:
        for item in ocr_results:
            if len(item) >= 3:
                box_pts, raw_text, score = item[0], item[1], item[2]
                text = unicodedata.normalize("NFC", str(raw_text or "").strip())
                if text:
                    lines.append(text)
                    try:
                        conf = float(score)
                        # Ensure confidence is clamped to ratio 0.0 <= score <= 1.0
                        conf = max(0.0, min(1.0, conf))
                        conf_scores.append(conf)
                    except (TypeError, ValueError):
                        conf = None

                    min_x = min(pt[0] for pt in box_pts)
                    min_y = min(pt[1] for pt in box_pts)
                    max_x = max(pt[0] for pt in box_pts)
                    max_y = max(pt[1] for pt in box_pts)
                    bounding_box = (float(min_x), float(min_y), float(max_x), float(max_y))

                    spans.append(
                        TextSpan(
                            text=text,
                            bounding_box=bounding_box,
                            confidence=conf,
                        )
                    )

    page_text = "\n".join(lines)

    page_confidence: ConfidenceValue | None = None
    if conf_scores:
        avg_score = sum(conf_scores) / len(conf_scores)
        page_confidence = ConfidenceValue(
            score=round(float(avg_score), 4),
            method="rapidocr_mean",
            evidence={
                "engine": "rapidocr-openvino",
                "backend": "openvino",
                "box_count": len(conf_scores),
            },
        )

    provenance = ProvenanceRecord(
        source_input_id=input_id,
        stage=_STAGE_NAME,
        plugin_id=_PLUGIN_ID,
        capability_id=_CAPABILITY_ID,
        page_number=page_number,
        evidence={
            "engine": "rapidocr-openvino",
            "backend": "openvino",
            "profile": "instant",
            "box_count": len(spans),
        },
    )

    metadata: dict[str, Any] = {}
    if page_confidence is not None:
        metadata["confidence"] = page_confidence.score

    page_data = PageData(
        page_number=page_number,
        text=page_text,
        spans=tuple(spans),
        metadata=metadata,
    )

    return page_data, provenance, page_confidence
