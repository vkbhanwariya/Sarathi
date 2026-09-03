"""RapidOCR + PP-OCRv5 + OpenVINO Engine Adapter for OCR Phase 1."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import stat
import unicodedata
from pathlib import Path
from typing import Any, Mapping

from sarathi.dosh import DoshError, FailureCode
from sarathi.sankalpa import (
    ConfidenceValue,
    DeviceType,
    ExecutionBinding,
    ExecutionProfile,
    PageData,
    ProvenanceRecord,
    TextSpan,
    WarningRecord,
)

from sarathi.sutra import get_canonical_data_root

_STAGE_NAME = "ocr"
_PLUGIN_ID = "shakti.ocr"
_CAPABILITY_ID = "ocr"
_CANONICAL_DATA_ROOT = get_canonical_data_root() / "ocr"
_REQUIRED_MODEL_KEYS = ("det", "rec", "cls")
_HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SAFE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")

_DEV_LANGS = frozenset({"devanagari", "hi", "hindi"})
_V6_LANGS = frozenset({"en_v6", "v6", "english_v6"})
_EN_LANGS = frozenset({"en", "eng", "english", "latin", "ch", "chinese"})
_ALL_SUPPORTED_LANGS = _DEV_LANGS | _V6_LANGS | _EN_LANGS


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


def _patch_rapidocr_openvino_device() -> None:
    """Ensure RapidOCR OpenVINOInferSession respects the device configured in the inference params."""
    try:
        import rapidocr.inference_engine.openvino.main as ov_main

        if getattr(ov_main.OpenVINOInferSession, "_sarathi_device_patched", False):
            return

        def _custom_init(self: Any, cfg: Any) -> None:
            from pathlib import Path

            try:
                from openvino import Core
            except ImportError:
                from openvino.runtime import Core

            device_name = str(cfg.get("device", "CPU")).upper()
            core = Core()
            model_path = Path(cfg.get("model_path"))
            self._verify_model(model_path)

            if device_name == "CPU":
                try:
                    from rapidocr.inference_engine.openvino.device_config import CPUConfig

                    cpu_config = CPUConfig(cfg.get("engine_cfg", {}))
                    core.set_property("CPU", cpu_config.get_config())
                except Exception:
                    pass

            self.model = core.read_model(model_path)
            compile_model = core.compile_model(model=self.model, device_name=device_name)
            self.session = compile_model.create_infer_request()

        ov_main.OpenVINOInferSession.__init__ = _custom_init
        ov_main.OpenVINOInferSession._sarathi_device_patched = True
    except Exception:
        pass


def extract_images_from_bytes(data: bytes) -> list[Any]:
    """Convert input file bytes (PDF or Image) into a list of PIL RGB images."""
    import pymupdf
    from PIL import Image, UnidentifiedImageError

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


def deskew_image(image_arr: Any) -> tuple[Any, float]:
    """Detect text orientation angle and apply affine rotation correction if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return image_arr, 0.0

        gray = cv2.cvtColor(image_arr, cv2.COLOR_RGB2GRAY) if len(image_arr.shape) == 3 else image_arr.copy()
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))

        if len(coords) < 100:
            return image_arr, 0.0

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle
        else:
            angle = -angle

        if 0.2 < abs(angle) < 45.0:
            (h, w) = image_arr.shape[:2]
            center = (w // 2, h // 2)
            m_rot = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                image_arr,
                m_rot,
                (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            return rotated, round(float(angle), 2)

        return image_arr, 0.0
    except Exception:
        return image_arr, 0.0


def is_low_contrast_image(image_arr: Any, std_threshold: float = 40.0) -> bool:
    """Check if image has low global contrast based on pixel intensity standard deviation."""
    try:
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return False
        if len(image_arr.shape) == 3:
            gray = 0.299 * image_arr[:, :, 0] + 0.587 * image_arr[:, :, 1] + 0.114 * image_arr[:, :, 2]
            return float(np.std(gray)) < std_threshold
        return float(np.std(image_arr)) < std_threshold
    except Exception:
        return False


def apply_clahe(image_arr: Any, clip_limit: float = 2.0, tile_grid_size: tuple[int, int] = (8, 8)) -> Any:
    """Apply Contrast Limited Adaptive Histogram Equalization (CLAHE) if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or image_arr.size == 0:
            return image_arr

        if len(image_arr.shape) == 3:
            lab = cv2.cvtColor(image_arr, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
            cl = clahe.apply(l)
            limg = cv2.merge((cl, a, b))
            return cv2.cvtColor(limg, cv2.COLOR_LAB2RGB)
        else:
            clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
            return clahe.apply(image_arr)
    except Exception:
        return image_arr


def remove_stamp_artifacts(image_arr: Any) -> Any:
    """Inpaint colored official rubber stamps that occlude underlying text if cv2 is available."""
    try:
        import cv2
        import numpy as np

        if not isinstance(image_arr, np.ndarray) or len(image_arr.shape) != 3 or image_arr.size == 0:
            return image_arr

        hsv = cv2.cvtColor(image_arr, cv2.COLOR_RGB2HSV)
        # Mask red and blue official rubber stamp pigments
        lower_red1 = np.array([0, 70, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 70, 50])
        upper_red2 = np.array([180, 255, 255])
        mask_r1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask_r2 = cv2.inRange(hsv, lower_red2, upper_red2)
        stamp_mask = mask_r1 | mask_r2

        if cv2.countNonZero(stamp_mask) > 100:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            stamp_mask = cv2.dilate(stamp_mask, kernel, iterations=1)
            return cv2.inpaint(image_arr, stamp_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)

        return image_arr
    except Exception:
        return image_arr


def preprocess_ocr_image(
    image_arr: Any,
    deskew: bool = True,
    clahe: bool = False,
    remove_stamps: bool = False,
) -> Any:
    """Run the pre-OCR vision enhancement pipeline with strict fallback when cv2 is unavailable."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        # Strict graceful fallback when OpenCV is not installed
        return image_arr

    out = image_arr
    if deskew:
        out, _ = deskew_image(out)
    if remove_stamps:
        out = remove_stamp_artifacts(out)
    if clahe:
        out = apply_clahe(out)
    return out


_ALPHANUMERIC_FILTER_RE = re.compile(r"[^\x20-\x7E₹€£\n\r\t]")
_HAS_ENGLISH_OR_DIGIT_RE = re.compile(r"[A-Za-z0-9]")


def filter_english_and_numbers(text: str) -> str:
    """Filter text to retain only English characters, numbers, and standard alphanumeric symbols."""
    cleaned = _ALPHANUMERIC_FILTER_RE.sub("", text)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    if not _HAS_ENGLISH_OR_DIGIT_RE.search(cleaned):
        return ""
    return cleaned


class TesseractFallbackAdapter:
    """Targeted Tesseract 5 fallback adapter for weak OCR bounding boxes."""

    def __init__(
        self,
        executable_path: Path | str | None = None,
        tessdata_dir: Path | str | None = None,
        language: str = "eng",
        timeout_seconds: float = 10.0,
    ) -> None:
        if executable_path is not None:
            self._executable_path: Path | None = Path(executable_path).resolve()
        else:
            import shutil

            candidates: list[Path] = []
            which_tess = shutil.which("tesseract")
            if which_tess:
                candidates.append(Path(which_tess).resolve())
            candidates.extend(
                [
                    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
                    Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
                ]
            )
            self._executable_path = next((p for p in candidates if p.exists() and p.is_file()), None)

        self._tessdata_dir: Path | None = Path(tessdata_dir).resolve() if tessdata_dir is not None else None
        self._language: str = language
        self._timeout_seconds: float = timeout_seconds

    def is_available(self) -> bool:
        """Return True only when fixed configured executable path exists on disk."""
        return self._executable_path is not None and self._executable_path.is_file()

    def recognize_crop(self, crop_image: Any, language: str | None = None) -> tuple[str, float | None]:
        """Run Tesseract 5 on cropped sub-image and return (text, confidence).

        Raises:
            DoshError(DEPENDENCY_UNAVAILABLE): If Tesseract is not configured or executable missing.
            DoshError(EXECUTION_FAILED): If subprocess execution fails, times out, or produces unusable output.
        """
        if not self.is_available() or self._executable_path is None:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="Tesseract fallback engine is not available at configured executable path.",
            )

        try:
            import pytesseract

            pytesseract.pytesseract.tesseract_cmd = str(self._executable_path)
        except ImportError:
            pass

        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_f:
            tmp_path = Path(tmp_f.name)

        active_lang = language or self._language
        cmd = [str(self._executable_path), str(tmp_path), "stdout", "--psm", "6", "-l", active_lang, "tsv"]
        if self._tessdata_dir is not None:
            cmd.extend(["--tessdata-dir", str(self._tessdata_dir)])

        try:
            crop_image.save(tmp_path)
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                check=False,
            )
            if res.returncode != 0:
                raise DoshError(
                    code=FailureCode.EXECUTION_FAILED,
                    message="Tesseract fallback execution returned non-zero exit status.",
                )

            stdout_text = res.stdout or ""
            lines = [ln for ln in stdout_text.splitlines() if ln.strip()]
            words: list[str] = []
            conf_scores: list[float] = []

            # Check for TSV format header
            if lines and ("\tconf\ttext" in lines[0] or lines[0].startswith("level\t")):
                has_invalid_conf = False
                for line in lines[1:]:
                    parts = line.split("\t")
                    if len(parts) >= 12:
                        word = parts[11].strip()
                        conf_str = parts[10].strip()
                        if word:
                            words.append(word)
                            try:
                                conf_num = float(conf_str)
                                # Tesseract TSV confidence is valid only when finite and within raw 0..100; convert once to 0..1
                                if not math.isnan(conf_num) and not math.isinf(conf_num) and 0.0 <= conf_num <= 100.0:
                                    conf_scores.append(conf_num / 100.0)
                                else:
                                    has_invalid_conf = True
                            except (ValueError, TypeError):
                                has_invalid_conf = True
                if not words:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Tesseract fallback produced unusable output.",
                    )
                text = unicodedata.normalize("NFC", " ".join(words))
                if has_invalid_conf or len(conf_scores) != len(words) or not conf_scores:
                    measured_conf = None
                else:
                    measured_conf = sum(conf_scores) / len(conf_scores)
                return text, measured_conf
            else:
                # Fallback for plain text output without TSV confidence
                plain_text = unicodedata.normalize("NFC", (res.stdout or "").strip())
                if not plain_text:
                    raise DoshError(
                        code=FailureCode.EXECUTION_FAILED,
                        message="Tesseract fallback produced unusable output.",
                    )
                return plain_text, None
        except (subprocess.SubprocessError, OSError, UnicodeDecodeError):
            raise DoshError(
                code=FailureCode.EXECUTION_FAILED,
                message="Tesseract fallback execution failed.",
            ) from None
        finally:
            tmp_path.unlink(missing_ok=True)


class RapidOCREngine:
    """Instance-owned RapidOCR + PP-OCRv5/v6 + OpenVINO engine adapter."""

    def __init__(
        self,
        data_root: Path | None = None,
        tesseract_adapter: TesseractFallbackAdapter | None = None,
        default_lang: str = "en",
    ) -> None:
        self._data_root: Path = data_root.resolve() if data_root is not None else _CANONICAL_DATA_ROOT
        self._engine: Any = None
        self._engines: dict[str, Any] = {}
        self._model_labels: dict[str, str] = {}
        self._default_lang: str = default_lang
        self._tesseract: TesseractFallbackAdapter = tesseract_adapter or TesseractFallbackAdapter()

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

        target_device = "CPU"
        if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
            target_device = execution_binding.backend_device_id or "GPU"

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
        for key in _REQUIRED_MODEL_KEYS:
            if key not in models_meta or not isinstance(models_meta[key], dict):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model manifest is missing required model entry.",
                )

        clean_lang = str(lang).lower().strip() if lang else self._default_lang
        if clean_lang in _V6_LANGS:
            engine_key = "v6_en"
            rec_key = "rec_v6_en"
        elif clean_lang in _DEV_LANGS:
            engine_key = "devanagari"
            rec_key = "rec_devanagari"
        else:
            engine_key = "en"
            rec_key = "rec"

        cache_key = f"{engine_key}:{target_device}"
        if cache_key in self._engines:
            return self._engines[cache_key]

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
            entry = models_meta[key]
            filename = entry.get("filename")
            expected_sha256 = entry.get("sha256")

            if (
                not _is_safe_filename(filename)
                or not isinstance(expected_sha256, str)
                or not _HEX_64_PATTERN.match(expected_sha256)
            ):
                raise DoshError(
                    code=FailureCode.DEPENDENCY_UNAVAILABLE,
                    message="Local OCR model manifest contains invalid model entry.",
                )

            entries[key] = (str(filename), expected_sha256)

        # Verify model assets on disk and validate SHA-256 checksums
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
            from rapidocr.utils.typings import LangRec, ModelType, OCRVersion
        except ImportError as exc:
            raise DoshError(
                code=FailureCode.DEPENDENCY_UNAVAILABLE,
                message="OCR dependencies are not installed. Install with 'uv add --optional ocr'.",
            ) from exc

        _patch_rapidocr_openvino_device()

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

        engine_inst = RapidOCR(params=params)
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
    ) -> tuple[PageData, ProvenanceRecord, ConfidenceValue | None, tuple[WarningRecord, ...]]:
        """Run PP-OCR OpenVINO on a single image and return factual PageData, Provenance, and Warnings."""
        import numpy as np

        target_device = "CPU"
        if execution_binding is not None and execution_binding.device_type == DeviceType.GPU:
            target_device = execution_binding.backend_device_id or "GPU"

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

            img_arr = preprocess_ocr_image(img_arr, deskew=deskew, clahe=clahe, remove_stamps=remove_stamps)

        output = engine(img_arr)

        spans: list[TextSpan] = []
        lines: list[str] = []
        conf_scores: list[float] = []
        warnings: list[WarningRecord] = []
        if applied_stamp_removal:
            warnings.append(
                WarningRecord(
                    code="EXPERIMENTAL_STAMP_REMOVAL",
                    message="Experimental stamp inpainting applied; visual fidelity altered.",
                    stage="ocr",
                )
            )
        has_invalid_confidence = False

        if target_lang in _DEV_LANGS and (custom_options is None or "english_numbers_only" not in custom_options):
            filter_opt = False
        else:
            filter_opt = custom_options.get("english_numbers_only", True) if custom_options else True

        if output and output.txts:
            for text_val, box_val, score_val in zip(
                output.txts,
                output.boxes if output.boxes is not None else [None] * len(output.txts),
                output.scores if output.scores is not None else [None] * len(output.txts),
            ):
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
                                        stage=_STAGE_NAME,
                                    )
                                )
                        except (TypeError, ValueError):
                            has_invalid_confidence = True
                            warnings.append(
                                WarningRecord(
                                    code="OCR_INVALID_CONFIDENCE",
                                    message="Engine returned non-numeric confidence value.",
                                    stage=_STAGE_NAME,
                                )
                            )
                    else:
                        has_invalid_confidence = True
                        warnings.append(
                            WarningRecord(
                                code="OCR_INVALID_CONFIDENCE",
                                message="Engine returned missing confidence value.",
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

        cache_key = f"{target_lang}:{target_device}"
        if target_lang in _DEV_LANGS:
            model_label = "PP-OCRv5-Devanagari"
        elif target_lang in _V6_LANGS:
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

        # Advanced profile processing
        fallback_applied = False

        if profile == ExecutionProfile.ACCURATE and spans:
            # Accurate mode: targeted Tesseract 5 fallback only for weak spans (< 0.65)
            tess_lang = "hin" if target_lang in _DEV_LANGS else "eng"
            for idx, span in enumerate(spans):
                if span.confidence is not None and span.confidence < 0.65 and span.bounding_box:
                    if not self._tesseract.is_available():
                        warnings.append(
                            WarningRecord(
                                code="OCR_FALLBACK_UNAVAILABLE",
                                message="Tesseract 5 fallback engine is not available on this host.",
                                stage=_STAGE_NAME,
                            )
                        )
                        break

                    min_x, min_y, max_x, max_y = span.bounding_box
                    w, h = image.size if hasattr(image, "size") else (int(max_x), int(max_y))
                    box_crop = (
                        max(0, int(min_x) - 2),
                        max(0, int(min_y) - 2),
                        min(w, int(max_x) + 2),
                        min(h, int(max_y) + 2),
                    )

                    if box_crop[2] > box_crop[0] and box_crop[3] > box_crop[1] and hasattr(image, "crop"):
                        cropped = image.crop(box_crop)
                        try:
                            try:
                                tess_res = self._tesseract.recognize_crop(cropped, language=tess_lang)
                            except TypeError:
                                tess_res = self._tesseract.recognize_crop(cropped)
                            if tess_res is not None:
                                tess_text, tess_conf = tess_res
                                if tess_conf is None:
                                    warnings.append(
                                        WarningRecord(
                                            code="OCR_FALLBACK_CONFIDENCE_UNAVAILABLE",
                                            message="Tesseract fallback confidence score is unavailable.",
                                            stage=_STAGE_NAME,
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
                            warnings.append(
                                WarningRecord(
                                    code="OCR_FALLBACK_FAILED",
                                    message="Tesseract 5 fallback execution failed.",
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

        if fallback_applied:
            # If Tesseract text replaces a RapidOCR span, do not retain page/run confidence labelled rapidocr_mean
            page_confidence = None

        final_page_text = "\n".join(lines) if lines else page_text
        metadata: dict[str, Any] = {"profile": profile.value}
        if page_confidence is not None:
            metadata["confidence"] = page_confidence.score

        evidence_dict: dict[str, Any] = {
            "engine": "rapidocr",
            "backend": "openvino",
            "device": target_device,
            "model": model_label,
            "scope": "english_and_numbers",
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
