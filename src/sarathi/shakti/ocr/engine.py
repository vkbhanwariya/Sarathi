"""RapidOCR + PP-OCRv5 + OpenVINO Engine Adapter for OCR Phase 1."""

from __future__ import annotations

import io
import math
from pathlib import Path
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

_STAGE_NAME = "ocr"
_PLUGIN_ID = "shakti.ocr"
_CAPABILITY_ID = "ocr"
_DEFAULT_MODEL_DIR = Path("data") / "ocr" / "models"


def extract_images_from_bytes(data: bytes) -> list[Any]:
    """Convert input file bytes (PDF or Image) into a list of PIL RGB images."""
    from PIL import Image, UnidentifiedImageError
    import pymupdf

    # 1. Check if PDF
    if data.startswith(b"%PDF-") or b"%PDF-" in data[:1024]:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, ValueError):
            return []

        images = []
        try:
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                images.append(img)
        finally:
            doc.close()
        return images

    # 2. Check if standard Image format
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")
        return [img]
    except (UnidentifiedImageError, OSError, ValueError):
        return []


class RapidOCREngine:
    """Instance-owned RapidOCR + PP-OCRv5 + OpenVINO engine adapter."""

    def __init__(self, model_root: Path | None = None) -> None:
        self._model_root: Path = model_root if model_root is not None else _DEFAULT_MODEL_DIR
        self._engine: Any = None

    def _get_engine(self) -> Any:
        """Lazily initialize the underlying RapidOCR engine instance."""
        if self._engine is None:
            try:
                from rapidocr import RapidOCR
                from rapidocr.inference_engine.base import EngineType
                from rapidocr.utils.typings import ModelType, OCRVersion
            except ImportError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="OCR dependencies are not installed. Install with 'uv add --optional ocr'.",
                ) from exc

            det_path = self._model_root / "ch_PP-OCRv5_det_mobile.onnx"
            rec_path = self._model_root / "ch_PP-OCRv5_rec_mobile.onnx"
            cls_path = self._model_root / "ch_ppocr_mobile_v2.0_cls_mobile.onnx"

            params: dict[str, Any] = {
                "Det.engine_type": EngineType.OPENVINO,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Rec.engine_type": EngineType.OPENVINO,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Cls.engine_type": EngineType.OPENVINO,
                "Global.log_level": "error",
            }
            if det_path.is_file():
                params["Det.model_path"] = str(det_path)
            if rec_path.is_file():
                params["Rec.model_path"] = str(rec_path)
            if cls_path.is_file():
                params["Cls.model_path"] = str(cls_path)

            self._engine = RapidOCR(params=params)
        return self._engine

    def ocr_page(
        self,
        image: Any,
        page_number: int,
        input_id: str,
    ) -> tuple[PageData, ProvenanceRecord, ConfidenceValue | None, tuple[WarningRecord, ...]]:
        """Run PP-OCRv5 OpenVINO on a single image and return factual PageData, Provenance, and Warnings."""
        import numpy as np

        engine = self._get_engine()
        img_arr = np.array(image)

        output = engine(img_arr)

        spans: list[TextSpan] = []
        lines: list[str] = []
        conf_scores: list[float] = []
        warnings: list[WarningRecord] = []

        if output and output.txts:
            for text_val, box_val, score_val in zip(
                output.txts,
                output.boxes if output.boxes is not None else [None] * len(output.txts),
                output.scores if output.scores is not None else [None] * len(output.txts),
            ):
                norm_text = unicodedata.normalize("NFC", str(text_val or "").strip())
                if norm_text:
                    lines.append(norm_text)
                    conf: float | None = None
                    if score_val is not None:
                        try:
                            score_float = float(score_val)
                            if not math.isnan(score_float) and not math.isinf(score_float) and 0.0 <= score_float <= 1.0:
                                conf = score_float
                                conf_scores.append(conf)
                            else:
                                warnings.append(
                                    WarningRecord(
                                        code="OCR_INVALID_CONFIDENCE",
                                        message="Engine returned out-of-bounds or non-finite confidence ratio.",
                                        stage=_STAGE_NAME,
                                    )
                                )
                        except (TypeError, ValueError):
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_CONFIDENCE",
                                    message="Engine returned non-numeric confidence value.",
                                    stage=_STAGE_NAME,
                                )
                            )

                    bounding_box: tuple[float, float, float, float] | None = None
                    if box_val is not None and len(box_val) >= 4:
                        try:
                            min_x = min(pt[0] for pt in box_val)
                            min_y = min(pt[1] for pt in box_val)
                            max_x = max(pt[0] for pt in box_val)
                            max_y = max(pt[1] for pt in box_val)
                            bounding_box = (float(min_x), float(min_y), float(max_x), float(max_y))
                        except Exception:
                            bounding_box = None

                    spans.append(
                        TextSpan(
                            text=norm_text,
                            bounding_box=bounding_box,
                            confidence=conf,
                        )
                    )

        page_text = "\n".join(lines)
        if not page_text.strip():
            warnings.append(
                WarningRecord(
                    code="OCR_EMPTY_PAGE",
                    message="No text detected on page.",
                    stage=_STAGE_NAME,
                )
            )

        page_confidence: ConfidenceValue | None = None
        if conf_scores:
            avg_score = sum(conf_scores) / len(conf_scores)
            page_confidence = ConfidenceValue(
                score=round(float(avg_score), 4),
                method="rapidocr_mean",
                evidence={
                    "engine": "rapidocr",
                    "backend": "openvino",
                    "model": "PP-OCRv5",
                    "box_count": len(conf_scores),
                },
            )

        metadata: dict[str, Any] = {}
        if page_confidence is not None:
            metadata["confidence"] = page_confidence.score

        provenance = ProvenanceRecord(
            source_input_id=input_id,
            stage=_STAGE_NAME,
            plugin_id=_PLUGIN_ID,
            capability_id=_CAPABILITY_ID,
            page_number=page_number,
            evidence={
                "engine": "rapidocr",
                "backend": "openvino",
                "model": "PP-OCRv5",
                "profile": "instant",
                "box_count": len(spans),
            },
        )

        page_data = PageData(
            page_number=page_number,
            text=page_text,
            spans=tuple(spans),
            metadata=metadata,
        )

        return page_data, provenance, page_confidence, tuple(warnings)
