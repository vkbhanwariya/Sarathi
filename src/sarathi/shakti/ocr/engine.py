"""RapidOCR + PP-OCRv5 + OpenVINO Engine Adapter for OCR Phase 1."""

from __future__ import annotations

import hashlib
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

_EXPECTED_MODELS: dict[str, dict[str, str]] = {
    "det": {
        "filename": "ch_PP-OCRv5_det_mobile.onnx",
        "sha256": "4d97c44a20d30a81aad087d6a396b08f786c4635742afc391f6621f5c6ae78ae",
    },
    "rec": {
        "filename": "ch_PP-OCRv5_rec_mobile.onnx",
        "sha256": "5825fc7ebf84ae7a412be049820b4d86d77620f204a041697b0494669b1742c5",
    },
    "cls": {
        "filename": "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "sha256": "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c",
    },
}


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
        """Lazily initialize the underlying RapidOCR engine instance after verifying assets."""
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

            verified_paths: dict[str, str] = {}
            for model_key, model_meta in _EXPECTED_MODELS.items():
                model_filename = model_meta["filename"]
                model_path = self._model_root / model_filename

                if not model_path.is_file():
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Required local OCR model asset '{model_filename}' is missing.",
                    )

                try:
                    actual_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Failed to read local OCR model asset '{model_filename}'.",
                    ) from exc

                if actual_sha256 != model_meta["sha256"]:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message=f"Local OCR model asset '{model_filename}' has invalid checksum.",
                    )

                verified_paths[model_key] = str(model_path)

            params: dict[str, Any] = {
                "Det.engine_type": EngineType.OPENVINO,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Det.model_path": verified_paths["det"],
                "Rec.engine_type": EngineType.OPENVINO,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.model_path": verified_paths["rec"],
                "Cls.engine_type": EngineType.OPENVINO,
                "Cls.model_path": verified_paths["cls"],
                "Global.log_level": "error",
            }

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
                    if box_val is not None:
                        try:
                            if len(box_val) < 4:
                                warnings.append(
                                    WarningRecord(
                                        code="OCR_INVALID_GEOMETRY",
                                        message="Engine returned bounding box with fewer than 4 points.",
                                        stage=_STAGE_NAME,
                                    )
                                )
                            else:
                                min_x = min(float(pt[0]) for pt in box_val)
                                min_y = min(float(pt[1]) for pt in box_val)
                                max_x = max(float(pt[0]) for pt in box_val)
                                max_y = max(float(pt[1]) for pt in box_val)
                                bounding_box = (min_x, min_y, max_x, max_y)
                        except (TypeError, ValueError, IndexError):
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_GEOMETRY",
                                    message="Engine returned malformed or non-numeric bounding box coordinates.",
                                    stage=_STAGE_NAME,
                                )
                            )

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
