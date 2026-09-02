"""Tests for Advanced OCR Modes: Accurate, Custom, and Deferred Layout Preserving."""

import importlib.util
from pathlib import Path
from typing import Any
import pytest
from PIL import Image, ImageDraw, ImageFont

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Kosh, Manthan
from sarathi.sankalpa import (
    CanonicalDocument,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    Request,
    Result,
)
from sarathi.shakti.ocr import OCRCapability
from sarathi.shakti.ocr.engine import RapidOCREngine, TesseractFallbackAdapter
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

_OCR_AVAILABLE = bool(
    importlib.util.find_spec("rapidocr")
    and importlib.util.find_spec("openvino")
    and importlib.util.find_spec("PIL")
    and importlib.util.find_spec("numpy")
)

pytestmark = pytest.mark.skipif(
    not _OCR_AVAILABLE,
    reason="Advanced OCR tests require optional OCR dependencies (rapidocr, openvino, PIL, numpy).",
)


class MockTesseractAdapter(TesseractFallbackAdapter):
    """Deterministic test adapter for targeted Tesseract fallback."""

    def __init__(self, available: bool = True, fallback_text: str = "TESSERACT_CORRECTED", confidence: float = 0.90) -> None:
        super().__init__()
        self._available = available
        self._fallback_text = fallback_text
        self._confidence = confidence
        self.call_count = 0

    def is_available(self) -> bool:
        return self._available

    def recognize_crop(self, crop_image: Any) -> tuple[str, float] | None:
        if not self._available:
            return None
        self.call_count += 1
        return self._fallback_text, self._confidence


def _create_clean_image(path: Path) -> None:
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((20, 20), "OFFICIAL GOVERNMENT ORDER", fill="black", font=font)
    draw.text((20, 50), "Date: 15/08/2026 Reference: REF-9900", fill="black", font=font)
    draw.text((20, 80), "Approved Amount: Rs 50,000.00", fill="black", font=font)
    img.save(path)


def test_accurate_profile_executes_and_preserves_clean_cases(tmp_path: Path) -> None:
    img_path = tmp_path / "clean_order.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-acc-1", "req-acc-1", "t-acc", "s-acc")
    inp = InputRef(input_id="inp-acc-1", source_path=img_path, display_name="clean_order.png", size_bytes=img_path.stat().st_size)

    req = Request(
        request_id="req-acc-1",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
    )

    result = cap.execute(req, ctx)

    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
    doc = result.data
    assert "GOVERNMENT" in doc.text or "ORDER" in doc.text
    assert doc.pages[0].metadata.get("profile") == "accurate"


def test_accurate_profile_targeted_tesseract_fallback_on_weak_spans(tmp_path: Path) -> None:
    img_path = tmp_path / "noisy_order.png"
    _create_clean_image(img_path)

    # Injected test adapter to test fallback when a weak span is detected
    test_tesseract = MockTesseractAdapter(available=True, fallback_text="GOVERNMENT ORDER VERIFIED", confidence=0.95)
    engine = RapidOCREngine(tesseract_adapter=test_tesseract)
    cap = OCRCapability(engine=engine)

    ctx = ExecutionContext("run-acc-2", "req-acc-2", "t-acc", "s-acc")
    inp = InputRef(input_id="inp-acc-2", source_path=img_path, display_name="noisy_order.png", size_bytes=img_path.stat().st_size)

    req = Request(
        request_id="req-acc-2",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
    )

    result = cap.execute(req, ctx)
    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)


def test_deferred_layout_preserving_profile_rejected_safely(tmp_path: Path) -> None:
    """Verify LAYOUT_PRESERVING is rejected as UNSUPPORTED until layout models are proven."""
    img_path = tmp_path / "table.png"
    _create_clean_image(img_path)

    kosh = Kosh()
    kosh.register_plugin(PLUGIN_INFO)
    kosh.register_capability(CAPABILITY_DECLARATION)
    manthan = Manthan(kosh)

    req = Request(
        request_id="req-lay-1",
        requirement="ocr",
        inputs=(InputRef(input_id="inp-1", source_path=img_path, display_name="table.png", size_bytes=10),),
        profile=ExecutionProfile.LAYOUT_PRESERVING,
    )

    # 1. Rejection at Manthan resolution
    with pytest.raises(DoshError) as exc_info:
        manthan.resolve(req)
    assert exc_info.value.code == FailureCode.UNSUPPORTED

    # 2. Rejection at direct capability execution
    cap = OCRCapability()
    ctx = ExecutionContext("run-lay", "req-lay-1", "t-lay", "s-lay")
    with pytest.raises(DoshError) as exc_exec:
        cap.execute(req, ctx)
    assert exc_exec.value.code == FailureCode.UNSUPPORTED


def test_custom_profile_validation_rejects_unsupported_engine(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-1", "req-cust-1", "t-cust", "s-cust")
    inp = InputRef(input_id="inp-cust-1", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size)

    bad_req = Request(
        request_id="req-cust-1",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"engine": "unsupported_cloud_engine"},
    )

    with pytest.raises(DoshError) as exc_info:
        cap.execute(bad_req, ctx)

    assert exc_info.value.code == FailureCode.VALIDATION_FAILED
    assert "not supported" in str(exc_info.value.message)


def test_custom_profile_executes_valid_options(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-2", "req-cust-2", "t-cust", "s-cust")
    inp = InputRef(input_id="inp-cust-2", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size)

    valid_req = Request(
        request_id="req-cust-2",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.CUSTOM,
        custom_options={"engine": "rapidocr", "binarize": True},
    )

    result = cap.execute(valid_req, ctx)
    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
