"""Verified RapidOCR + OpenVINO Engine Instance Factory for Sarathi.

Verifies model weights on disk against the local cryptographic manifest and
synthesizes device-specific RapidOCR parameters for execution.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from sarathi.dosh import DoshError, FailureCode
from sarathi.shakti.ocr.engine.common import EN_LANGS
from sarathi.shakti.ocr.engine.openvino import patch_rapidocr_openvino_device
from sarathi.shakti.ocr.engine.readiness import verify_ocr_manifest_and_models


def resolve_engine_keys(lang: str, default_lang: str = "devanagari") -> tuple[str, str]:
    """Resolve engine key and recognition model key based on target language.

    Routing policy:
    - English, Latin, v6 -> PP-OCRv6 Small (rec_v6_en)
    - Hindi, Devanagari, mixed Hindi+English, or default -> PP-OCRv5 Devanagari (rec_devanagari)
    """
    clean_lang = str(lang).lower().strip() if lang else default_lang
    if clean_lang in EN_LANGS:
        return "v6_en", "rec_v6_en"
    return "devanagari", "rec_devanagari"


def build_rapidocr_instance(
    data_root: Path,
    lang: str,
    target_device: str,
    verified_model_paths: dict[str, str],
    default_lang: str = "devanagari",
) -> tuple[Any, str, str, str]:
    """Build and initialize a verified RapidOCR engine instance.

    Returns:
        (engine_instance, cache_key, engine_key, model_label)
    """
    engine_key, rec_key = resolve_engine_keys(lang, default_lang=default_lang)
    cache_key = f"{engine_key}:{target_device}"

    # Verify required models using shared readiness validator (zero duplicate manifest/hash code)
    verified_paths = verify_ocr_manifest_and_models(
        data_root=data_root,
        target_keys=("det", "cls", rec_key),
        verified_cache=verified_model_paths,
    )

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

    if engine_key == "v6_en":
        params: dict[str, Any] = {
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
            "Rec.text_score": 0.0,
            "Cls.engine_type": EngineType.OPENVINO,
            "Cls.device": target_device,
            "Cls.model_path": verified_paths["cls"],
            "Global.log_level": "error",
        }
        label = "PP-OCRv6"
    else:  # devanagari (default, Hindi, and mixed Hindi+English)
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
            "Rec.lang_type": LangRec.DEVANAGARI,
            "Rec.model_path": verified_paths[rec_key],
            "Rec.rec_batch_num": rec_batch_num,
            "Rec.text_score": 0.0,
            "Cls.engine_type": EngineType.OPENVINO,
            "Cls.device": target_device,
            "Cls.model_path": verified_paths["cls"],
            "Global.log_level": "error",
        }
        label = "PP-OCRv5-Devanagari"

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

    return engine_inst, cache_key, engine_key, label


__all__ = [
    "build_rapidocr_instance",
    "resolve_engine_keys",
]
