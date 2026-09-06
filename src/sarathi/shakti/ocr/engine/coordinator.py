"""RapidOCR + PP-OCRv5/v6 + OpenVINO engine coordinator and readiness verifier."""

from __future__ import annotations

import hashlib
import json
import math
import stat
import threading
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    CancellationToken,
    ConfidenceValue,
    ExecutionBinding,
    ExecutionProfile,
    PageData,
    ProvenanceRecord,
    TextSpan,
    WarningRecord,
)
from sarathi.shakti.ocr.engine.common import (
    CANONICAL_DATA_ROOT,
    DEV_LANGS,
    HEX_64_PATTERN,
    REQUIRED_MODEL_KEYS,
    STAGE_NAME,
    V6_LANGS,
)
from sarathi.shakti.ocr.engine.openvino import (
    disable_openvino_telemetry,
    is_safe_filename,
    patch_rapidocr_openvino_device,
    resolve_target_device,
)
from sarathi.shakti.ocr.engine.preprocessing import (
    is_low_contrast_image,
    preprocess_ocr_image,
)
from sarathi.shakti.ocr.engine.tesseract import (
    TesseractFallbackAdapter,
    filter_english_and_numbers,
)


def check_ocr_readiness(data_root: Path | None = None) -> tuple[bool, str]:
    """Verify that all required OCR dependencies, manifest, and model files are factually valid.

    Returns:
        (is_ready, status_or_reason)
    """
    disable_openvino_telemetry()
    import importlib.util

    for mod in ("rapidocr", "openvino", "PIL", "numpy"):
        if importlib.util.find_spec(mod) is None:
            return False, "Unavailable (Missing required OCR Python libraries)"

    target_root = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
    manifest_file = target_root / "manifest.json"
    models_dir = target_root / "models"

    try:
        if not manifest_file.exists() or manifest_file.is_symlink() or not manifest_file.is_file():
            return False, "Unavailable (OCR model manifest is missing or invalid)"
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or "models" not in manifest or not isinstance(manifest["models"], dict):
            return False, "Unavailable (OCR model manifest structure is invalid)"

        if not models_dir.exists() or models_dir.is_symlink() or not models_dir.is_dir():
            return False, "Unavailable (OCR models directory is missing or invalid)"

        models_meta = manifest["models"]
        for key in ("det", "rec", "cls", "rec_devanagari", "rec_v6_en"):
            if key not in models_meta or not isinstance(models_meta[key], dict):
                return False, f"Unavailable (OCR model manifest is missing required model entry '{key}')"
            entry = models_meta[key]
            filename = entry.get("filename")
            expected_sha = entry.get("sha256")
            if not filename or not expected_sha or not is_safe_filename(filename):
                return False, f"Unavailable (OCR model specification for '{key}' is invalid)"

            model_path = models_dir / filename
            if not model_path.exists() or model_path.is_symlink() or not model_path.is_file():
                return False, f"Unavailable (Required OCR model asset '{key}' is missing)"

            h = hashlib.sha256()
            with open(model_path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            if h.hexdigest().lower() != expected_sha.lower():
                return False, f"Unavailable (OCR model asset '{key}' checksum mismatch)"

        return True, "Ready (RapidOCR + OpenVINO)"
    except Exception:
        return False, "Unavailable (OCR preflight verification failed)"


def _parse_rapidocr_output(
    output: Any,
    filter_opt: bool = True,
) -> tuple[list[str], list[TextSpan], list[float], list[WarningRecord], bool, bool]:
    lines: list[str] = []
    spans: list[TextSpan] = []
    conf_scores: list[float] = []
    warnings: list[WarningRecord] = []
    has_invalid_confidence = False
    has_invalid_geometry = False

    if output and getattr(output, "txts", None):
        import itertools

        raw_txts = list(output.txts)
        raw_boxes = list(output.boxes) if getattr(output, "boxes", None) is not None else []
        raw_scores = list(output.scores) if getattr(output, "scores", None) is not None else []
        if (raw_boxes and len(raw_boxes) != len(raw_txts)) or (raw_scores and len(raw_scores) != len(raw_txts)):
            warnings.append(
                WarningRecord(
                    code="OCR_METADATA_LENGTH_MISMATCH",
                    message="Engine output text, box, and score counts disagree; unaligned items padded safely.",
                    stage=STAGE_NAME,
                )
            )

        for text_val, box_val, score_val in itertools.zip_longest(
            raw_txts, raw_boxes, raw_scores, fillvalue=None
        ):
            if text_val is None:
                continue
            norm_text = unicodedata.normalize("NFC", str(text_val or "").strip())
            if filter_opt:
                norm_text = filter_english_and_numbers(norm_text)
            if norm_text:
                lines.append(norm_text)
                conf: float | None = None
                if score_val is not None:
                    try:
                        score_float = float(score_val)
                        if (
                            not math.isnan(score_float)
                            and not math.isinf(score_float)
                            and 0.0 <= score_float <= 1.0
                        ):
                            conf = score_float
                            conf_scores.append(conf)
                        else:
                            has_invalid_confidence = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_CONFIDENCE",
                                    message="Engine returned out-of-bounds or non-finite confidence ratio.",
                                    stage=STAGE_NAME,
                                )
                            )
                    except (TypeError, ValueError):
                        has_invalid_confidence = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_INVALID_CONFIDENCE",
                                message="Engine returned non-numeric confidence value.",
                                stage=STAGE_NAME,
                            )
                        )
                else:
                    has_invalid_confidence = True
                    warnings.append(
                        WarningRecord(
                            code="OCR_INVALID_CONFIDENCE",
                            message="Engine returned missing confidence value.",
                            stage=STAGE_NAME,
                        )
                    )

                bounding_box: tuple[float, float, float, float] | None = None
                if box_val is not None:
                    try:
                        if len(box_val) < 4:
                            has_invalid_geometry = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_GEOMETRY",
                                    message="Engine returned bounding box with fewer than 4 points.",
                                    stage=STAGE_NAME,
                                )
                            )
                        else:
                            min_x = min(float(pt[0]) for pt in box_val)
                            min_y = min(float(pt[1]) for pt in box_val)
                            max_x = max(float(pt[0]) for pt in box_val)
                            max_y = max(float(pt[1]) for pt in box_val)
                            if any(math.isnan(v) or math.isinf(v) for v in (min_x, min_y, max_x, max_y)):
                                has_invalid_geometry = True
                                warnings.append(
                                    WarningRecord(
                                        code="OCR_INVALID_GEOMETRY",
                                        message="Engine returned non-finite bounding box coordinates.",
                                        stage=STAGE_NAME,
                                    )
                                )
                            else:
                                bounding_box = (min_x, min_y, max_x, max_y)
                    except (TypeError, ValueError, IndexError):
                        has_invalid_geometry = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_INVALID_GEOMETRY",
                                message="Engine returned malformed or non-numeric bounding box coordinates.",
                                stage=STAGE_NAME,
                            )
                        )

                spans.append(
                    TextSpan(
                        text=norm_text,
                        bounding_box=bounding_box,
                        confidence=conf,
                    )
                )

    return lines, spans, conf_scores, warnings, has_invalid_confidence, has_invalid_geometry


class RapidOCREngine:
    """Instance-owned RapidOCR + PP-OCRv5/v6 + OpenVINO engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        tesseract_adapter: TesseractFallbackAdapter | None = None,
        default_lang: str = "en",
    ) -> None:
        self._data_root: Path = data_root.resolve() if data_root is not None else CANONICAL_DATA_ROOT
        self._engine: Any = None
        self._engines: dict[str, Any] = {}
        self._model_labels: dict[str, str] = {}
        self._default_lang: str = default_lang
        self._tesseract: TesseractFallbackAdapter = tesseract_adapter or TesseractFallbackAdapter()
        self._init_lock: threading.Lock = threading.Lock()
        self._local: threading.local = threading.local()
        self._verified_model_paths: dict[str, str] = {}

    @property
    def default_lang(self) -> str:
        return self._default_lang

    @property
    def tesseract(self) -> TesseractFallbackAdapter:
        return self._tesseract

    def _get_engine(self, lang: str = "en", execution_binding: ExecutionBinding | None = None) -> Any:
        """Lazily initialize the underlying RapidOCR engine instance for the requested language after verifying assets against manifest.json."""
        if self._engine is not None:
            return self._engine

        if not hasattr(self._local, "engines"):
            self._local.engines = {}

        clean_lang = str(lang).lower().strip() if lang else self._default_lang
        if clean_lang in V6_LANGS:
            engine_key = "v6_en"
        elif clean_lang in DEV_LANGS:
            engine_key = "devanagari"
        else:
            engine_key = "en"

        target_device = resolve_target_device(execution_binding)
        cache_key = f"{engine_key}:{target_device}"

        if cache_key in self._local.engines:
            return self._local.engines[cache_key]

        if cache_key in self._engines:
            cand = self._engines[cache_key]
            try:
                from rapidocr import RapidOCR

                if not isinstance(cand, RapidOCR):
                    return cand
            except ImportError:
                return cand
            if getattr(cand, "_owner_thread", None) == threading.get_ident():
                return cand

        with self._init_lock:
            if cache_key in self._local.engines:
                return self._local.engines[cache_key]
            return self._get_engine_unlocked(lang=lang, execution_binding=execution_binding)

    def _get_engine_unlocked(self, lang: str = "en", execution_binding: ExecutionBinding | None = None) -> Any:
        target_device = resolve_target_device(execution_binding)

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

        if (
            not isinstance(manifest_dict, dict)
            or "models" not in manifest_dict
            or not isinstance(manifest_dict["models"], dict)
        ):
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

        # 1. Base required model keys
        for key in REQUIRED_MODEL_KEYS:
            if key not in models_meta or not isinstance(models_meta[key], dict):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model manifest is missing required model entry.",
                )

        clean_lang = str(lang).lower().strip() if lang else self._default_lang
        if clean_lang in V6_LANGS:
            engine_key = "v6_en"
            rec_key = "rec_v6_en"
        elif clean_lang in DEV_LANGS:
            engine_key = "devanagari"
            rec_key = "rec_devanagari"
        else:
            engine_key = "en"
            rec_key = "rec"

        cache_key = f"{engine_key}:{target_device}"
        if hasattr(self._local, "engines") and cache_key in self._local.engines:
            return self._local.engines[cache_key]
        if cache_key in self._engines:
            cand = self._engines[cache_key]
            try:
                from rapidocr import RapidOCR

                if not isinstance(cand, RapidOCR):
                    return cand
            except ImportError:
                return cand
            if getattr(cand, "_owner_thread", None) == threading.get_ident():
                return cand

        # 2. Validate target recognition model entry
        if rec_key not in models_meta or not isinstance(models_meta[rec_key], dict):
            if engine_key == "devanagari":
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Devanagari OCR model is missing from manifest.",
                )
            elif engine_key == "v6_en":
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="PP-OCRv6 English OCR model is missing from manifest.",
                )
            else:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model manifest is missing required model entry.",
                )

        target_keys = ("det", "cls", rec_key)
        verified_paths: dict[str, str] = {}
        entries: dict[str, tuple[str, str]] = {}

        for key in target_keys:
            if key in self._verified_model_paths:
                verified_paths[key] = self._verified_model_paths[key]
                continue

            entry = models_meta[key]
            filename = entry.get("filename")
            expected_sha256 = entry.get("sha256")

            if (
                not is_safe_filename(filename)
                or not isinstance(expected_sha256, str)
                or not HEX_64_PATTERN.match(expected_sha256)
            ):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model manifest contains invalid model entry.",
                )

            entries[key] = (str(filename), expected_sha256)

        # Verify model assets on disk and validate SHA-256 checksums if not already verified
        for key, (filename, expected_sha256) in entries.items():
            model_path = models_dir / filename
            try:
                model_stat = model_path.lstat()
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Required local OCR model asset is missing.",
                ) from exc

            if stat.S_ISLNK(model_stat.st_mode) or not stat.S_ISREG(model_stat.st_mode):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Required local OCR model asset is not a regular file.",
                )

            h = hashlib.sha256()
            try:
                with open(model_path, "rb") as f:
                    while chunk := f.read(65536):
                        h.update(chunk)
            except OSError as exc:
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Failed to read local OCR model asset.",
                ) from exc

            actual_sha256 = h.hexdigest().lower()
            if actual_sha256 != expected_sha256.lower():
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model asset has invalid checksum.",
                )

            verified_paths[key] = str(model_path)
            self._verified_model_paths[key] = str(model_path)

        try:
            from rapidocr import RapidOCR
            from rapidocr.inference_engine.base import EngineType
            from rapidocr.utils.typings import LangRec, ModelType, OCRVersion
        except ImportError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="OCR dependencies are not installed. Install with 'uv add --optional ocr'.",
            ) from exc

        patch_rapidocr_openvino_device()

        if engine_key == "devanagari":
            params: dict[str, Any] = {
                "Det.engine_type": EngineType.OPENVINO,
                "Det.device": target_device,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Det.model_path": verified_paths["det"],
                "Rec.engine_type": EngineType.OPENVINO,
                "Rec.device": target_device,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.lang_type": LangRec.DEVANAGARI,
                "Rec.model_path": verified_paths[rec_key],
                "Cls.engine_type": EngineType.OPENVINO,
                "Cls.device": target_device,
                "Cls.model_path": verified_paths["cls"],
                "Global.log_level": "error",
            }
        elif engine_key == "v6_en":
            params = {
                "Det.engine_type": EngineType.OPENVINO,
                "Det.device": target_device,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Det.model_path": verified_paths["det"],
                "Rec.engine_type": EngineType.OPENVINO,
                "Rec.device": target_device,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
                "Rec.model_type": ModelType.SMALL,
                "Rec.model_path": verified_paths[rec_key],
                "Cls.engine_type": EngineType.OPENVINO,
                "Cls.device": target_device,
                "Cls.model_path": verified_paths["cls"],
                "Global.log_level": "error",
            }
        else:
            params = {
                "Det.engine_type": EngineType.OPENVINO,
                "Det.device": target_device,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.model_type": ModelType.MOBILE,
                "Det.model_path": verified_paths["det"],
                "Rec.engine_type": EngineType.OPENVINO,
                "Rec.device": target_device,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.model_path": verified_paths[rec_key],
                "Cls.engine_type": EngineType.OPENVINO,
                "Cls.device": target_device,
                "Cls.model_path": verified_paths["cls"],
                "Global.log_level": "error",
            }

        try:
            engine_inst = RapidOCR(params=params)
        except DoshError:
            raise
        except Exception as exc:
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message=f"Failed to initialize OCR engine on device '{target_device}'.",
            ) from exc
        setattr(engine_inst, "_owner_thread", threading.get_ident())
        if not hasattr(self._local, "engines"):
            self._local.engines = {}
        self._local.engines[cache_key] = engine_inst
        self._engines[cache_key] = engine_inst
        self._engines[engine_key] = engine_inst
        if rec_key == "rec_v6_en":
            label = "PP-OCRv6"
        elif rec_key == "rec_devanagari":
            label = "PP-OCRv5-Devanagari"
        else:
            label = "PP-OCRv5"
        self._model_labels[cache_key] = label
        self._model_labels[engine_key] = label
        return engine_inst

    def ocr_page(
        self,
        image: Any,
        page_number: int,
        input_id: str,
        profile: ExecutionProfile = ExecutionProfile.INSTANT,
        custom_options: Mapping[str, Any] | None = None,
        execution_binding: ExecutionBinding | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[PageData, ProvenanceRecord, ConfidenceValue | None, tuple[WarningRecord, ...]]:
        """Run PP-OCR OpenVINO on a single image and return factual PageData, Provenance, and Warnings."""
        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        import numpy as np

        target_device = resolve_target_device(execution_binding)
        lang_opt = custom_options.get("lang") if custom_options else None
        target_lang = str(lang_opt).lower().strip() if lang_opt else self._default_lang
        engine = self._get_engine(target_lang, execution_binding=execution_binding)
        img_arr = np.array(image)

        # Resolve preprocessing flags per execution profile and options
        is_lightweight = custom_options.get("lightweight", False) if custom_options else False
        preprocess_requested = custom_options.get("preprocess") if custom_options else None
        should_preprocess = (preprocess_requested is not False) and not is_lightweight
        applied_stamp_removal = False

        if should_preprocess:
            if profile == ExecutionProfile.INSTANT:
                # Minimum beneficial preprocessing per OCR Veda: deskew only when beneficial, no destructive filters
                deskew = custom_options.get("deskew", True) if custom_options else True
                clahe = custom_options.get("clahe", False) if custom_options else False
            else:
                # Accurate / Custom: adaptive preprocessing where evidence supports it
                deskew = custom_options.get("deskew", True) if custom_options else True
                if custom_options and "clahe" in custom_options:
                    clahe = bool(custom_options["clahe"])
                else:
                    clahe = is_low_contrast_image(img_arr)

            # Stamp removal is destructive and strictly opt-in per Veda safety rules
            remove_stamps = bool(
                custom_options.get("remove_stamps", False) or custom_options.get("inpaint_stamps", False)
            ) if custom_options else False

            if remove_stamps:
                applied_stamp_removal = True

            import sarathi.shakti.ocr.engine as ocr_engine

            img_arr = ocr_engine.preprocess_ocr_image(img_arr, deskew=deskew, clahe=clahe, remove_stamps=remove_stamps)

        # Synchronize preprocessed image for geometrically aligned cropping
        from PIL import Image

        is_binarized = False
        if profile == ExecutionProfile.CUSTOM and custom_options and custom_options.get("binarize"):
            is_binarized = True
            if isinstance(img_arr, np.ndarray):
                gray_pil = Image.fromarray(img_arr).convert("L")
            elif hasattr(image, "convert"):
                gray_pil = image.convert("L")
            else:
                gray_pil = Image.fromarray(np.array(image)).convert("L")
            threshold_img = gray_pil.point(lambda p: 255 if p > 128 else 0)
            processed_img = threshold_img
            img_arr = np.array(threshold_img.convert("RGB"))
        else:
            if isinstance(img_arr, np.ndarray):
                processed_img = Image.fromarray(img_arr)
            elif hasattr(image, "copy"):
                processed_img = image.copy()
            else:
                processed_img = image

        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        output = engine(img_arr)

        if cancellation_token is not None and cancellation_token.is_cancelled:
            cancellation_token.check_cancelled()

        if target_lang in DEV_LANGS and (custom_options is None or "english_numbers_only" not in custom_options):
            filter_opt = False
        else:
            filter_opt = custom_options.get("english_numbers_only", True) if custom_options else True

        lines, spans, conf_scores, parse_warnings, has_invalid_confidence, has_invalid_geometry = (
            _parse_rapidocr_output(output, filter_opt=filter_opt)
        )
        warnings: list[WarningRecord] = list(parse_warnings)
        if applied_stamp_removal:
            warnings.append(
                WarningRecord(
                    code="EXPERIMENTAL_STAMP_REMOVAL",
                    message="Experimental stamp inpainting applied; visual fidelity altered.",
                    stage="ocr",
                )
            )

        # Advanced profile processing
        fallback_applied = False
        fallback_required = False
        fallback_unavailable = False
        fallback_failed = False

        # Accurate mode or Custom with fallback_enabled: targeted Tesseract fallback only for weak spans (< 0.65)
        fallback_enabled = (
            (custom_options.get("fallback_enabled", True) if custom_options else True)
            if profile == ExecutionProfile.ACCURATE
            else (bool(custom_options.get("fallback_enabled", False)) if custom_options else False)
        )
        if (profile in (ExecutionProfile.ACCURATE, ExecutionProfile.CUSTOM)) and fallback_enabled and spans:
            tess_lang = "hin" if target_lang in DEV_LANGS else "eng"
            for idx, span in enumerate(spans):
                if span.confidence is not None and span.confidence < 0.65 and span.bounding_box:
                    fallback_required = True
                    if not self._tesseract.is_available():
                        fallback_unavailable = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_FALLBACK_UNAVAILABLE",
                                message="Tesseract 5 fallback engine is not available on this host.",
                                stage=STAGE_NAME,
                            )
                        )
                        break

                    min_x, min_y, max_x, max_y = span.bounding_box
                    w, h = processed_img.size if hasattr(processed_img, "size") else (int(max_x), int(max_y))
                    box_crop = (
                        max(0, int(min_x) - 2),
                        max(0, int(min_y) - 2),
                        min(w, int(max_x) + 2),
                        min(h, int(max_y) + 2),
                    )

                    if box_crop[2] > box_crop[0] and box_crop[3] > box_crop[1] and hasattr(processed_img, "crop"):
                        cropped = processed_img.crop(box_crop)
                        try:
                            tess_res = self._tesseract.recognize_crop(cropped, language=tess_lang)
                            if tess_res is not None:
                                tess_text, tess_conf = tess_res
                                if tess_conf is None:
                                    warnings.append(
                                        WarningRecord(
                                            code="OCR_FALLBACK_CONFIDENCE_UNAVAILABLE",
                                            message="Tesseract fallback confidence score is unavailable.",
                                            stage=STAGE_NAME,
                                        )
                                    )
                                if tess_conf is not None and tess_conf > span.confidence:
                                    spans[idx] = TextSpan(
                                        text=tess_text,
                                        confidence=tess_conf,
                                        bounding_box=span.bounding_box,
                                    )
                                    if idx < len(lines):
                                        lines[idx] = tess_text
                                        fallback_applied = True
                        except DoshError:
                            fallback_failed = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_FALLBACK_FAILED",
                                    message="Tesseract 5 fallback execution failed.",
                                    stage=STAGE_NAME,
                                )
                            )

        final_page_text = "\n".join(lines)
        if not final_page_text.strip():
            warnings.append(
                WarningRecord(
                    code="OCR_EMPTY_PAGE",
                    message="No text detected on page.",
                    stage=STAGE_NAME,
                )
            )

        cache_key = f"{target_lang}:{target_device}"
        if target_lang in DEV_LANGS:
            model_label = "PP-OCRv5-Devanagari"
        elif target_lang in V6_LANGS:
            model_label = "PP-OCRv6"
        else:
            model_label = self._model_labels.get(cache_key, self._model_labels.get(f"en:{target_device}", "PP-OCRv5"))

        page_confidence: ConfidenceValue | None = None
        if conf_scores and not has_invalid_confidence and len(conf_scores) == len(spans):
            avg_score = sum(conf_scores) / len(conf_scores)
            page_confidence = ConfidenceValue(
                score=round(float(avg_score), 4),
                method="rapidocr_mean",
                evidence={
                    "engine": "rapidocr",
                    "backend": "openvino",
                    "device": target_device,
                    "model": model_label,
                    "box_count": len(conf_scores),
                },
            )

        if fallback_applied:
            # If Tesseract text replaces a RapidOCR span, do not retain page/run confidence labelled rapidocr_mean
            page_confidence = None

        # Determine deterministic validation outcome
        val_enabled = custom_options.get("validation_enabled", True) if custom_options else True
        validation_outcome: str
        if not val_enabled:
            validation_outcome = "skipped"
        elif not final_page_text.strip():
            validation_outcome = "empty"
        elif has_invalid_confidence:
            validation_outcome = "invalid_confidence"
        elif has_invalid_geometry:
            validation_outcome = "invalid_geometry"
        elif fallback_applied:
            validation_outcome = "fallback_improved"
        elif fallback_failed:
            validation_outcome = "fallback_failed"
        elif fallback_unavailable:
            validation_outcome = "fallback_unavailable"
        elif fallback_required:
            validation_outcome = "weak_confidence"
        else:
            validation_outcome = "usable"

        if target_lang in DEV_LANGS:
            scope = "full_devanagari"
        elif filter_opt:
            scope = "english_and_numbers"
        else:
            scope = "multilingual"

        metadata: dict[str, Any] = {
            "profile": profile.value,
            "validation_outcome": validation_outcome,
            "model": model_label,
            "scope": scope,
        }
        if page_confidence is not None:
            metadata["confidence"] = page_confidence.score

        evidence_dict: dict[str, Any] = {
            "engine": "rapidocr",
            "backend": "openvino",
            "device": target_device,
            "model": model_label,
            "scope": scope,
            "profile": profile.value,
            "box_count": len(spans),
            "validation_outcome": validation_outcome,
        }
        if is_binarized:
            evidence_dict["binarized"] = True
        if fallback_applied:
            evidence_dict["fallback_engine"] = "tesseract5"
            evidence_dict["fallback_applied"] = True
        elif fallback_required:
            evidence_dict["fallback_engine"] = "tesseract5"
            evidence_dict["fallback_status"] = (
                "unavailable" if fallback_unavailable else ("failed" if fallback_failed else "unimproved")
            )

        provenance = ProvenanceRecord(
            source_input_id=input_id,
            stage=STAGE_NAME,
            plugin_id="shakti.ocr",
            capability_id="ocr",
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
