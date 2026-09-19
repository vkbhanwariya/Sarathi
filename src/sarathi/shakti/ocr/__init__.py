"""OCR Phase 1 Capability for Sarathi.

Exposes:
- OCRCapability: Executable capability implementing RapidOCR + PP-OCRv5 + OpenVINO execution.
- RapidOCREngine: Instance adapter for RapidOCR execution.
- CAPABILITY_DECLARATION: Declaration metadata for registration in Kosh.
- PLUGIN_INFO: Plugin registration info.
"""

from __future__ import annotations

from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

__all__ = [
    "CAPABILITY_DECLARATION",
    "OCRCapability",
    "PLUGIN_INFO",
    "RapidOCREngine",
    "check_ocr_readiness",
]


from sarathi.shakti.text.lazy import lazy_exports

lazy_exports(
    globals(),
    {
        "OCRCapability": ".capability:OCRCapability",
        "RapidOCREngine": ".engine:RapidOCREngine",
        "check_ocr_readiness": ".engine:check_ocr_readiness",
    },
)
