"""OCR Phase 1 Capability for Sarathi.

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
    "configure_pytesseract",
    "find_tesseract_executable",
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
    if name == "configure_pytesseract":
        from sarathi.shakti.ocr.engine import configure_pytesseract

        return configure_pytesseract
    if name == "find_tesseract_executable":
        from sarathi.shakti.ocr.engine import find_tesseract_executable

        return find_tesseract_executable
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Auto-configure pytesseract and environment paths if Tesseract is installed
try:
    from sarathi.shakti.ocr.engine import configure_pytesseract

    configure_pytesseract()
except Exception:
    pass
