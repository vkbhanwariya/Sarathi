"""RapidOCR + OpenVINO Engine Package Façade."""

from __future__ import annotations

from sarathi.shakti.ocr.engine.common import (
    _ALL_SUPPORTED_LANGS,
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
from sarathi.shakti.ocr.engine.layout import (
    detect_ruled_tables,
    group_paragraphs,
    reconstruct_layout,
)
from sarathi.shakti.ocr.engine.openvino import (
    _resolve_target_device,
    disable_openvino_telemetry,
    is_safe_filename,
    patch_rapidocr_openvino_device,
    resolve_target_device,
)
from sarathi.shakti.ocr.engine.parser import (
    filter_english_and_numbers,
    sort_reading_order_xycut,
)
from sarathi.shakti.ocr.engine.preprocessing import (
    apply_clahe,
    deskew_image,
    is_low_contrast_image,
    preprocess_ocr_image,
    remove_stamp_artifacts,
)
from sarathi.shakti.ocr.engine.rasterize import (
    BoundedPageRasterizer,
    extract_images_from_bytes,
    iter_images_from_bytes,
)

__all__ = [
    "ALL_SUPPORTED_LANGS",
    "BoundedPageRasterizer",
    "DEV_LANGS",
    "EN_LANGS",
    "RapidOCREngine",
    "V6_LANGS",
    "_ALL_SUPPORTED_LANGS",
    "_parse_rapidocr_output",
    "_resolve_target_device",
    "apply_clahe",
    "check_ocr_readiness",
    "deskew_image",
    "detect_ruled_tables",
    "disable_openvino_telemetry",
    "extract_images_from_bytes",
    "filter_english_and_numbers",
    "group_paragraphs",
    "is_low_contrast_image",
    "is_safe_filename",
    "iter_images_from_bytes",
    "patch_rapidocr_openvino_device",
    "preprocess_ocr_image",
    "reconstruct_layout",
    "remove_stamp_artifacts",
    "resolve_target_device",
    "sort_reading_order_xycut",
]
