"""Verified RapidOCR + OpenVINO Engine Instance Factory for Sarathi.

Verifies model weights on disk against the local cryptographic manifest and
synthesizes device-specific RapidOCR parameters for execution.
"""

from __future__ import annotations

import hashlib
import json
import stat
import threading
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.ocr.engine.common import (
    DEV_LANGS,
    HEX_64_PATTERN,
    REQUIRED_MODEL_KEYS,
    V6_LANGS,
)
from sarathi.shakti.ocr.engine.openvino import (
    is_safe_filename,
    patch_rapidocr_openvino_device,
)


def resolve_engine_keys(lang: str, default_lang: str = "en") -> tuple[str, str]:
    """Resolve engine key and recognition model key based on target language."""
    clean_lang = str(lang).lower().strip() if lang else default_lang
    if clean_lang in V6_LANGS:
        return "v6_en", "rec_v6_en"
    elif clean_lang in DEV_LANGS:
        return "devanagari", "rec_devanagari"
    else:
        return "en", "rec"


def build_rapidocr_instance(
    data_root: Path,
    lang: str,
    target_device: str,
    verified_model_paths: dict[str, str],
    default_lang: str = "en",
) -> tuple[Any, str, str, str]:
    """Build and initialize a verified RapidOCR engine instance.

    Returns:
        (engine_instance, cache_key, engine_key, model_label)
    """
    manifest_file = data_root / "manifest.json"
    models_dir = data_root / "models"

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

    engine_key, rec_key = resolve_engine_keys(lang, default_lang=default_lang)
    cache_key = f"{engine_key}:{target_device}"

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
        if key in verified_model_paths:
            verified_paths[key] = verified_model_paths[key]
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
        verified_model_paths[key] = str(model_path)

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

    rec_batch_num = 16 if target_device == "CPU" else 32
    box_thresh = 0.55

    if engine_key == "devanagari":
        params: dict[str, Any] = {
            "Det.engine_type": EngineType.OPENVINO,
            "Det.device": target_device,
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Det.model_type": ModelType.MOBILE,
            "Det.model_path": verified_paths["det"],
            "Det.box_thresh": box_thresh,
            "Rec.engine_type": EngineType.OPENVINO,
            "Rec.device": target_device,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.lang_type": LangRec.DEVANAGARI,
            "Rec.model_path": verified_paths[rec_key],
            "Rec.rec_batch_num": rec_batch_num,
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
            "Det.box_thresh": box_thresh,
            "Rec.engine_type": EngineType.OPENVINO,
            "Rec.device": target_device,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.model_type": ModelType.SMALL,
            "Rec.model_path": verified_paths[rec_key],
            "Rec.rec_batch_num": rec_batch_num,
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
            "Det.box_thresh": box_thresh,
            "Rec.engine_type": EngineType.OPENVINO,
            "Rec.device": target_device,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
            "Rec.model_path": verified_paths[rec_key],
            "Rec.rec_batch_num": rec_batch_num,
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

    if rec_key == "rec_v6_en":
        label = "PP-OCRv6"
    elif rec_key == "rec_devanagari":
        label = "PP-OCRv5-Devanagari"
    else:
        label = "PP-OCRv5"

    return engine_inst, cache_key, engine_key, label
