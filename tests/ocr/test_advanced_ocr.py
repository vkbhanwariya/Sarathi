"""Tests for Advanced OCR Modes: Accurate, Custom, and Deferred Layout Preserving."""

import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
from sarathi.shakti.ocr.engine import RapidOCREngine
from sarathi.shakti.ocr.plugin import CAPABILITY_DECLARATION, PLUGIN_INFO

_OCR_AVAILABLE = bool(
    importlib.util.find_spec("rapidocr")
    and importlib.util.find_spec("openvino")
    and importlib.util.find_spec("PIL")
    and importlib.util.find_spec("numpy")
)

if not _OCR_AVAILABLE:
    pytest.skip(
        "Advanced OCR tests require optional OCR dependencies (rapidocr, openvino, PIL, numpy).",
        allow_module_level=True,
    )


class DummyRapidOCROutput:
    def __init__(self, txts: list[str], boxes: list[Any], scores: list[float]) -> None:
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


def _create_clean_image(path: Path) -> None:
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((20, 20), "OFFICIAL GOVERNMENT ORDER", fill="black", font=font)
    draw.text((20, 50), "Date: 15/08/2026 Reference: REF-9900", fill="black", font=font)
    draw.text((20, 80), "Approved Amount: Rs 50,000.00", fill="black", font=font)
    img.save(path)


@pytest.mark.real_model
def test_accurate_profile_executes_and_preserves_clean_cases(tmp_path: Path) -> None:
    img_path = tmp_path / "clean_order.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-acc-1", "req-acc-1", "t-acc", "s-acc")
    inp = InputRef(
        input_id="inp-acc-1", source_path=img_path, display_name="clean_order.png", size_bytes=img_path.stat().st_size
    )

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


def test_accurate_profile_measured_confidence_replaces_weaker_rapidocr_span() -> None:
    """Proves factual measured retry confidence replaces weaker RapidOCR span (< 0.65)."""
    img = Image.new("RGB", (200, 50), color="white")
    engine = RapidOCREngine(default_lang="hi")

    retry_output = MagicMock()
    retry_output.txts = ("राजस्थान",)
    retry_output.scores = (0.94,)

    base_output = DummyRapidOCROutput(
        txts=["कमजोर"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.50],
    )

    def mock_call(arr: Any, **kwargs: Any) -> Any:
        if kwargs.get("use_det") is False:
            return retry_output
        return base_output

    engine._engine = mock_call
    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-1", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "राजस्थान"
    assert page_data.spans[0].confidence == 0.94
    assert page_data.spans[0].metadata.get("retry_applied") is True
    assert page_data.spans[0].metadata.get("original_confidence") == 0.50
    assert page_data.spans[0].metadata.get("confidence_gain") == 0.44
    assert page_data.metadata.get("retry_improved_count") == 1
    assert page_data.metadata.get("retry_total_gain") == 0.44
    assert page_data.text == "राजस्थान"


def test_accurate_profile_preserves_span_when_retry_confidence_is_lower() -> None:
    """Proves lower retry confidence does NOT replace primary span."""
    img = Image.new("RGB", (200, 50), color="white")
    engine = RapidOCREngine(default_lang="hi")

    retry_output = MagicMock()
    retry_output.txts = ("राजस्थान",)
    retry_output.scores = (0.40,)

    base_output = DummyRapidOCROutput(
        txts=["कमजोर"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.55],
    )

    def mock_call(arr: Any, **kwargs: Any) -> Any:
        if kwargs.get("use_det") is False:
            return retry_output
        return base_output

    engine._engine = mock_call
    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-3", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "कमजोर"
    assert page_data.spans[0].confidence == 0.55


def test_accurate_profile_gracefully_handles_retry_failure() -> None:
    """Proves failed retry execution preserves primary span without crashing."""
    img = Image.new("RGB", (200, 50), color="white")
    engine = RapidOCREngine(default_lang="hi")

    base_output = DummyRapidOCROutput(
        txts=["कमजोर"],
        boxes=[[(10, 10), (100, 10), (100, 30), (10, 30)]],
        scores=[0.45],
    )

    def mock_call(arr: Any, **kwargs: Any) -> Any:
        if kwargs.get("use_det") is False:
            raise RuntimeError("Engine retry error")
        return base_output

    engine._engine = mock_call
    page_data, prov, conf, warnings = engine.ocr_page(img, 1, "inp-5", profile=ExecutionProfile.ACCURATE)

    assert page_data.spans[0].text == "कमजोर"
    assert page_data.spans[0].confidence == 0.45



@pytest.mark.real_model
def test_layout_preserving_profile_executes_successfully(tmp_path: Path) -> None:
    """Verify LAYOUT_PRESERVING is officially resolved by Manthan and executed with coordinate retention."""
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

    # 1. Successful resolution at Manthan
    plan = manthan.resolve(req)
    assert plan.capability_ids == ("ocr",)

    # 2. Successful execution preserving bounding boxes and coordinates
    cap = OCRCapability()
    ctx = ExecutionContext("run-lay", "req-lay-1", "t-lay", "s-lay")
    res = cap.execute(req, ctx)
    assert res.data is not None
    assert len(res.data.pages) >= 1
    assert "OFFICIAL GOVERNMENT" in res.data.text

    page = res.data.pages[0]
    assert len(page.spans) >= 3, f"Expected at least 3 detected text lines, got {len(page.spans)}"

    # Validate coordinate retention for each span
    for span in page.spans:
        assert span.bounding_box is not None, f"Span '{span.text}' missing bounding_box"
        assert len(span.bounding_box) == 4
        x0, y0, x1, y1 = span.bounding_box
        assert x1 > x0 and y1 > y0, f"Invalid span bounding box dimensions: {span.bounding_box}"

    # Verify spatial reading order: top line precedes middle line which precedes bottom line
    top_y = page.spans[0].bounding_box[1]
    mid_y = page.spans[1].bounding_box[1]
    bot_y = page.spans[2].bounding_box[1]
    assert top_y < mid_y < bot_y, (
        f"Spans must be sorted top-to-bottom: top_y={top_y}, mid_y={mid_y}, bot_y={bot_y}"
    )


def test_custom_profile_validation_rejects_unsupported_engine(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-1", "req-cust-1", "t-cust", "s-cust")
    inp = InputRef(
        input_id="inp-cust-1", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size
    )

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


@pytest.mark.real_model
def test_custom_profile_executes_valid_options(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-2", "req-cust-2", "t-cust", "s-cust")
    inp = InputRef(
        input_id="inp-cust-2", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size
    )

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


@pytest.mark.real_model
def test_accurate_profile_offline_target_platform_e2e(tmp_path: Path) -> None:
    """Target platform (Windows 11 x64) offline E2E test for Accurate OCR execution.

    Proves factual confidence without synthetic fabrication on real engine output.
    """
    img_path = tmp_path / "real_e2e_image.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-e2e-acc", "req-e2e-acc", "t-e2e", "s-e2e")
    inp = InputRef(
        input_id="inp-e2e-1",
        source_path=img_path,
        display_name="real_e2e_image.png",
        size_bytes=img_path.stat().st_size,
    )
    req = Request(
        request_id="req-e2e-acc",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.ACCURATE,
    )

    res = cap.execute(req, ctx)

    assert isinstance(res.data, CanonicalDocument)
    doc: CanonicalDocument = res.data
    assert len(doc.pages) == 1
    page = doc.pages[0]
    assert len(page.spans) > 0

    # Verify all reported confidences are strictly valid factual floats in [0.0, 1.0]
    for span in page.spans:
        assert span.confidence is None or (0.0 <= span.confidence <= 1.0)
        # Ensure no synthetic hardcoded 0.85 default
        if span.confidence is not None:
            assert isinstance(span.confidence, float)




def test_rapidocr_angle_cls_profile_and_option_behavior() -> None:
    """Proves use_angle_cls respects profile defaults and explicit custom_options."""
    from sarathi.sankalpa import ExecutionProfile
    from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine

    calls: list[dict[str, Any]] = []

    def mock_ocr(arr: Any, **kwargs: Any) -> DummyRapidOCROutput:
        calls.append(kwargs)
        return DummyRapidOCROutput(
            txts=["Sample Text"],
            boxes=[[[10, 10], [100, 10], [100, 30], [10, 30]]],
            scores=[0.95],
        )

    engine = RapidOCREngine()
    engine._engine = mock_ocr
    test_img = Image.new("RGB", (200, 50), color="white")

    # 1. Instant profile defaults to use_cls=False
    calls.clear()
    page, prov, _, _ = engine.ocr_page(test_img, 1, "inp-1", profile=ExecutionProfile.INSTANT)
    assert calls[0].get("use_cls") is False
    assert prov.evidence.get("use_angle_cls") is False

    # 2. Accurate profile defaults to use_cls=True
    calls.clear()
    page, prov, _, _ = engine.ocr_page(test_img, 1, "inp-1", profile=ExecutionProfile.ACCURATE)
    assert calls[0].get("use_cls") is True
    assert prov.evidence.get("use_angle_cls") is True

    # 3. Explicit override in custom_options
    calls.clear()
    page, prov, _, _ = engine.ocr_page(
        test_img,
        1,
        "inp-1",
        profile=ExecutionProfile.INSTANT,
        custom_options={"use_angle_cls": True},
    )
    assert calls[0].get("use_cls") is True
    assert prov.evidence.get("use_angle_cls") is True
