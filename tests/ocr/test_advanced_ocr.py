"""Tests for Advanced OCR Modes: Accurate, Layout Preserving, and Custom."""

import importlib.util
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFont

from sarathi.dosh import DoshError, FailureCode
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


def _create_clean_image(path: Path) -> None:
    img = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((20, 20), "OFFICIAL GOVERNMENT ORDER", fill="black", font=font)
    draw.text((20, 50), "Date: 15/08/2026 Reference: REF-9900", fill="black", font=font)
    draw.text((20, 80), "Approved Amount: Rs 50,000.00", fill="black", font=font)
    img.save(path)


def _create_table_image(path: Path) -> None:
    img = Image.new("RGB", (700, 200), color="white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    # Header
    draw.text((20, 20), "DATE", fill="black", font=font)
    draw.text((150, 20), "DESCRIPTION", fill="black", font=font)
    draw.text((350, 20), "AMOUNT", fill="black", font=font)
    # Row 1
    draw.text((20, 50), "01/08/2026", fill="black", font=font)
    draw.text((150, 50), "Salary Credit", fill="black", font=font)
    draw.text((350, 50), "50,000.00", fill="black", font=font)
    # Row 2
    draw.text((20, 80), "05/08/2026", fill="black", font=font)
    draw.text((150, 80), "Rent Payment", fill="black", font=font)
    draw.text((350, 80), "15,000.00", fill="black", font=font)
    img.save(path)


def test_accurate_profile_executes_successfully(tmp_path: Path) -> None:
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


def test_layout_preserving_profile_extracts_tables(tmp_path: Path) -> None:
    img_path = tmp_path / "table_doc.png"
    _create_table_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-lay-1", "req-lay-1", "t-lay", "s-lay")
    inp = InputRef(input_id="inp-lay-1", source_path=img_path, display_name="table_doc.png", size_bytes=img_path.stat().st_size)

    req = Request(
        request_id="req-lay-1",
        requirement="ocr",
        inputs=(inp,),
        profile=ExecutionProfile.LAYOUT_PRESERVING,
    )

    result = cap.execute(req, ctx)

    assert isinstance(result, Result)
    assert isinstance(result.data, CanonicalDocument)
    doc = result.data
    assert len(doc.pages) == 1
    assert doc.pages[0].metadata.get("profile") == "layout_preserving"
    # Verify structured tables extraction if present
    if doc.pages[0].tables:
        t = doc.pages[0].tables[0]
        assert len(t.headers) > 0 or len(t.rows) > 0


def test_custom_profile_validation_rejects_unsupported_engine(tmp_path: Path) -> None:
    img_path = tmp_path / "doc.png"
    _create_clean_image(img_path)

    cap = OCRCapability()
    ctx = ExecutionContext("run-cust-1", "req-cust-1", "t-cust", "s-cust")
    inp = InputRef(input_id="inp-cust-1", source_path=img_path, display_name="doc.png", size_bytes=img_path.stat().st_size)

    # Unsupported engine choice
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
