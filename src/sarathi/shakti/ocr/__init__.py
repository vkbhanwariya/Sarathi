"""OCR Phase 1 Capability for Sarathi V2.

Exposes:
- OCRCapability: Executable capability implementing RapidOCR + PP-OCRv5 + OpenVINO execution.
- RapidOCREngine: Instance adapter for RapidOCR execution.
- CAPABILITY_DECLARATION: Declaration metadata for registration in Kosh.
- PLUGIN_INFO: Plugin registration info.
"""

from __future__ import annotations

from typing import Any

from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "CAPABILITY_DECLARATION",
    "OCRCapability",
    "PLUGIN_INFO",
    "RapidOCREngine",
    "check_ocr_readiness",
]


def __getattr__(name: str) -> Any:
    if name == "OCRCapability":
        from sarathi.shakti.ocr.capability import OCRCapability

        return OCRCapability
    if name == "RapidOCREngine":
        from sarathi.shakti.ocr.engine import RapidOCREngine

        return RapidOCREngine
    if name == "check_ocr_readiness":
        from sarathi.shakti.ocr.engine import check_ocr_readiness

        return check_ocr_readiness
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
