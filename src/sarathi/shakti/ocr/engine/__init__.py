"""RapidOCR + PP-OCRv5/v6 + OpenVINO Engine Package Façade."""

from __future__ import annotations

from sarathi.shakti.ocr.engine.common import (
    _ALL_SUPPORTED_LANGS,
    _DEV_LANGS,
    _EN_LANGS,
    _V6_LANGS,
    ALL_SUPPORTED_LANGS,
    DEV_LANGS,
    EN_LANGS,
    V6_LANGS,
)
from sarathi.shakti.ocr.engine.coordinator import (
    RapidOCREngine,
    _parse_rapidocr_output,
    check_ocr_readiness,
)
from sarathi.shakti.ocr.engine.openvino import (
    _disable_openvino_telemetry,
    _is_safe_filename,
    _patch_rapidocr_openvino_device,
    _resolve_target_device,
    disable_openvino_telemetry,
    is_safe_filename,
    patch_rapidocr_openvino_device,
    resolve_target_device,
)
from sarathi.shakti.ocr.engine.preprocessing import (
    apply_clahe,
    deskew_image,
    is_low_contrast_image,
    preprocess_ocr_image,
    remove_stamp_artifacts,
)
from sarathi.shakti.ocr.engine.rasterize import extract_images_from_bytes
from sarathi.shakti.ocr.engine.tesseract import (
    TesseractFallbackAdapter,
    configure_pytesseract,
    filter_english_and_numbers,
    find_tesseract_executable,
)

__all__ = [
    "RapidOCREngine",
    "TesseractFallbackAdapter",
    "apply_clahe",
    "check_ocr_readiness",
    "configure_pytesseract",
    "deskew_image",
    "disable_openvino_telemetry",
    "extract_images_from_bytes",
    "filter_english_and_numbers",
    "find_tesseract_executable",
    "is_low_contrast_image",
    "is_safe_filename",
    "patch_rapidocr_openvino_device",
    "preprocess_ocr_image",
    "remove_stamp_artifacts",
    "resolve_target_device",
]
