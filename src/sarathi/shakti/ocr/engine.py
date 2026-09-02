"""RapidOCR + PP-OCRv5 + OpenVINO Engine Adapter for OCR Phase 1."""

from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
from typing import Any
import unicodedata

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ConfidenceValue,
    ExecutionProfile,
    TableData,
    PageData,
    ProvenanceRecord,
    TextSpan,
    WarningRecord,
)

_STAGE_NAME = "ocr"
_PLUGIN_ID = "shakti.ocr"
_CAPABILITY_ID = "ocr"
_CANONICAL_DATA_ROOT = Path(__file__).resolve().parents[4] / "data" / "ocr"
_REQUIRED_MODEL_KEYS = ("det", "rec", "cls")
_HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _is_safe_filename(name: Any) -> bool:
    """Validate that filename is a safe, non-empty basename without path traversal or separators."""
    if not isinstance(name, str):
        return False
    clean = name.strip()
    if not clean or clean in (".", ".."):
        return False
    if "/" in clean or "\\" in clean or ":" in clean:
        return False
    if not _SAFE_FILENAME_PATTERN.match(clean):
        return False
    return True


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


class TesseractFallbackAdapter:
    """Targeted Tesseract 5 fallback adapter for weak OCR bounding boxes."""

    def __init__(self) -> None:
        self._is_available: bool | None = None

    def is_available(self) -> bool:
        if self._is_available is None:
            import shutil
            self._is_available = shutil.which("tesseract") is not None
        return self._is_available

    def recognize_crop(self, crop_image: Any) -> tuple[str, float] | None:
        """Run Tesseract 5 on cropped sub-image and return (text, confidence)."""
        if not self.is_available():
            return None
        import subprocess
        import tempfile
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_f:
                tmp_path = Path(tmp_f.name)
            crop_image.save(tmp_path)

            res = subprocess.run(
                ["tesseract", str(tmp_path), "stdout", "--psm", "6"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            tmp_path.unlink(missing_ok=True)
            if res.returncode == 0 and res.stdout:
                text = unicodedata.normalize("NFC", res.stdout.strip())
                if text:
                    return text, 0.85
        except (OSError, subprocess.SubprocessError):
            pass
        return None

class RapidOCREngine:
    """Instance-owned RapidOCR + PP-OCRv5 + OpenVINO engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        tesseract_adapter: TesseractFallbackAdapter | None = None,
    ) -> None:
        self._data_root: Path = data_root.resolve() if data_root is not None else _CANONICAL_DATA_ROOT
        self._engine: Any = None
        self._tesseract: TesseractFallbackAdapter = tesseract_adapter or TesseractFallbackAdapter()

    def _get_engine(self) -> Any:
        """Lazily initialize the underlying RapidOCR engine instance after verifying assets against manifest.json."""
        if self._engine is None:
            manifest_file = self._data_root / "manifest.json"
            models_dir = self._data_root / "models"

            try:
                manifest_stat = manifest_file.lstat()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Required local OCR model manifest is missing.",
                ) from exc

            if stat.S_ISLNK(manifest_stat.st_mode) or not stat.S_ISREG(manifest_stat.st_mode):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Required local OCR model manifest is invalid or not a regular file.",
                )

            try:
                manifest_dict = json.loads(manifest_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Failed to read or parse local OCR model manifest.",
                ) from exc

            if not isinstance(manifest_dict, dict) or "models" not in manifest_dict or not isinstance(manifest_dict["models"], dict):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model manifest has an invalid structure.",
                )

            try:
                models_dir_stat = models_dir.lstat()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Required local OCR model directory is missing.",
                ) from exc

            if stat.S_ISLNK(models_dir_stat.st_mode) or not stat.S_ISDIR(models_dir_stat.st_mode):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Required local OCR model directory is invalid or a symlink.",
                )

            models_meta = manifest_dict["models"]
            verified_paths: dict[str, str] = {}
            entries: dict[str, tuple[str, str]] = {}

            # 1. Validate manifest structure for all required model keys
            for key in _REQUIRED_MODEL_KEYS:
                if key not in models_meta or not isinstance(models_meta[key], dict):
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message="Local OCR model manifest is missing required model entry.",
                    )
                entry = models_meta[key]
                filename = entry.get("filename")
                expected_sha256 = entry.get("sha256")

                if not _is_safe_filename(filename) or not isinstance(expected_sha256, str) or not _HEX_64_PATTERN.match(expected_sha256):
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message="Local OCR model manifest contains invalid model entry.",
                    )

                entries[key] = (str(filename), expected_sha256)

            # 2. Verify model assets on disk and validate SHA-256 checksums
            for key, (filename, expected_sha256) in entries.items():
                model_path = models_dir / filename
                try:
                    st = model_path.lstat()
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message="Required local OCR model asset is missing.",
                    ) from exc

                if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message="Required local OCR model asset is not a regular file.",
                    )

                try:
                    actual_sha256 = hashlib.sha256(model_path.read_bytes()).hexdigest()
                except OSError as exc:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message="Failed to read local OCR model asset.",
                    ) from exc

                if actual_sha256 != expected_sha256:
                    raise DoshError(
                        code=FailureCode.DEPENDENCY_UNAVAILABLE,
                        message="Local OCR model asset has invalid checksum.",
                    )

                verified_paths[key] = str(model_path)

            try:
                from rapidocr import RapidOCR
                from rapidocr.inference_engine.base import EngineType
                from rapidocr.utils.typings import ModelType, OCRVersion
            except ImportError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="OCR dependencies are not installed. Install with 'uv add --optional ocr'.",
                ) from exc

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
        profile: ExecutionProfile = ExecutionProfile.INSTANT,
        custom_options: Mapping[str, Any] | None = None,
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
                                if any(math.isnan(v) or math.isinf(v) for v in (min_x, min_y, max_x, max_y)):
                                    warnings.append(
                                        WarningRecord(
                                            code="OCR_INVALID_GEOMETRY",
                                            message="Engine returned non-finite bounding box coordinates.",
                                            stage=_STAGE_NAME,
                                        )
                                    )
                                else:
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

        # Advanced profile processing
        fallback_applied = False

        if profile == ExecutionProfile.ACCURATE and spans:
            # Accurate mode: targeted Tesseract 5 fallback only for weak spans (< 0.65)
            for idx, span in enumerate(spans):
                if span.confidence is not None and span.confidence < 0.65 and span.bounding_box:
                    min_x, min_y, max_x, max_y = span.bounding_box
                    w, h = image.size if hasattr(image, "size") else (int(max_x), int(max_y))
                    box_crop = (max(0, int(min_x) - 2), max(0, int(min_y) - 2), min(w, int(max_x) + 2), min(h, int(max_y) + 2))

                    if box_crop[2] > box_crop[0] and box_crop[3] > box_crop[1] and hasattr(image, "crop"):
                        cropped = image.crop(box_crop)
                        tess_res = self._tesseract.recognize_crop(cropped)
                        if tess_res is not None:
                            tess_text, tess_conf = tess_res
                            if tess_conf > span.confidence:
                                spans[idx] = TextSpan(
                                    text=tess_text,
                                    confidence=tess_conf,
                                    bounding_box=span.bounding_box,
                                )
                                if idx < len(lines):
                                    lines[idx] = tess_text
                                fallback_applied = True
                        elif not self._tesseract.is_available():
                            warnings.append(
                                WarningRecord(
                                    code="OCR_FALLBACK_UNAVAILABLE",
                                    message="Tesseract 5 fallback engine is not available on this host.",
                                    stage=_STAGE_NAME,
                                )
                            )

        elif profile == ExecutionProfile.CUSTOM:
            if custom_options and custom_options.get("binarize") and hasattr(image, "convert"):
                gray = image.convert("L")
                threshold_img = gray.point(lambda p: 255 if p > 128 else 0)
                cust_out = engine(np.array(threshold_img))
                if cust_out and cust_out.txts:
                    lines = [unicodedata.normalize("NFC", str(t).strip()) for t in cust_out.txts if str(t).strip()]

        final_page_text = "\n".join(lines) if lines else page_text
        metadata: dict[str, Any] = {"profile": profile.value}
        if page_confidence is not None:
            metadata["confidence"] = page_confidence.score

        evidence_dict: dict[str, Any] = {
            "engine": "rapidocr",
            "backend": "openvino",
            "model": "PP-OCRv5",
            "profile": profile.value,
            "box_count": len(spans),
        }
        if fallback_applied:
            evidence_dict["fallback_engine"] = "tesseract5"
            evidence_dict["fallback_applied"] = True

        provenance = ProvenanceRecord(
            source_input_id=input_id,
            stage=_STAGE_NAME,
            plugin_id=_PLUGIN_ID,
            capability_id=_CAPABILITY_ID,
            page_number=page_number,
            evidence=evidence_dict,
        )

        page_data = PageData(
            page_number=page_number,
            text=final_page_text,
            spans=tuple(spans),
            tables=(),
            metadata=metadata,
        )

        return page_data, provenance, page_confidence, tuple(warnings)
