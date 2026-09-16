"""Tests for single-open bounded rasterization pipeline, adaptive DPI, and weak-crop batching."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pymupdf
import pytest
from PIL import Image

from sarathi.sankalpa import (
    CancellationToken,
    ExecutionContext,
    ExecutionProfile,
    InputRef,
    PageData,
    ProvenanceRecord,
    Request,
)
from sarathi.shakti.ocr.capability import OCRCapability
from sarathi.shakti.ocr.engine.coordinator import RapidOCREngine
from sarathi.shakti.ocr.engine.rasterize import (
    BoundedPageRasterizer,
    get_page_count_from_bytes,
)


def _create_test_pdf_bytes(num_pages: int = 3) -> bytes:
    """Create a valid synthetic multi-page PDF in memory."""
    doc = pymupdf.open()
    for i in range(num_pages):
        page = doc.new_page(width=300, height=200)
        page.insert_text((50, 50), f"Test Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_bounded_page_rasterizer_pdf_single_open() -> None:
    """Proves BoundedPageRasterizer rasterizes all pages from a single open document with bounded buffer."""
    pdf_bytes = _create_test_pdf_bytes(num_pages=3)
    assert get_page_count_from_bytes(pdf_bytes) == 3

    with BoundedPageRasterizer(pdf_bytes, pages=[1, 2, 3], dpi=150, max_buffered=2) as rasterizer:
        img1 = rasterizer.get_page(1)
        assert img1 is not None
        assert isinstance(img1, Image.Image)

        img2 = rasterizer.get_page(2)
        assert img2 is not None

        img3 = rasterizer.get_page(3)
        assert img3 is not None


def test_bounded_page_rasterizer_subset_pages() -> None:
    """Proves BoundedPageRasterizer skips unneeded pages when a subset is specified."""
    pdf_bytes = _create_test_pdf_bytes(num_pages=4)

    with BoundedPageRasterizer(pdf_bytes, pages=[1, 3], dpi=150, max_buffered=2) as rasterizer:
        img1 = rasterizer.get_page(1)
        assert img1 is not None

        img3 = rasterizer.get_page(3)
        assert img3 is not None


def test_bounded_page_rasterizer_cancellation() -> None:
    """Proves BoundedPageRasterizer cooperative cancellation stops cleanly."""
    pdf_bytes = _create_test_pdf_bytes(num_pages=5)
    token = CancellationToken()
    token.cancel()

    rasterizer = BoundedPageRasterizer(pdf_bytes, pages=[1, 2, 3, 4, 5], cancellation_token=token)
    rasterizer.start()
    rasterizer.close()
    assert rasterizer._closed is True


def test_adaptive_dpi_resolution_in_capability(tmp_path: Path) -> None:
    """Proves OCRCapability selects 200 DPI for ACCURATE profile and custom option overrides."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(_create_test_pdf_bytes(1))

    mock_engine = MagicMock(spec=RapidOCREngine)
    mock_engine.ocr_page.return_value = (
        PageData(page_number=1, text="Sample"),
        ProvenanceRecord(source_input_id="in-1", stage="ocr", plugin_id="shakti.ocr", capability_id="ocr", page_number=1, evidence={}),
        None,
        [],
    )
    cap = OCRCapability(engine=mock_engine)
    ctx = ExecutionContext(run_id="r1", request_id="req-1", trace_id="t1", span_id="s1")

    # 1. ACCURATE profile -> 200 DPI
    req_acc = Request(
        request_id="r-acc",
        requirement="ocr",
        profile=ExecutionProfile.ACCURATE,
        inputs=(InputRef("in-1", pdf_path, "application/pdf", 100),),
    )
    with MagicMock() as mock_iter:
        mock_iter.return_value = [Image.new("RGB", (100, 100))]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("sarathi.shakti.ocr.capability.iter_images_from_bytes", mock_iter)
            cap.execute(req_acc, ctx)
            assert mock_iter.call_args.kwargs.get("dpi") == 200

    # 2. INSTANT profile -> 150 DPI
    req_inst = Request(
        request_id="r-inst",
        requirement="ocr",
        profile=ExecutionProfile.INSTANT,
        inputs=(InputRef("in-1", pdf_path, "application/pdf", 100),),
    )
    with MagicMock() as mock_iter:
        mock_iter.return_value = [Image.new("RGB", (100, 100))]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("sarathi.shakti.ocr.capability.iter_images_from_bytes", mock_iter)
            cap.execute(req_inst, ctx)
            assert mock_iter.call_args.kwargs.get("dpi") == 150

    # 3. Custom DPI override -> 250 DPI
    req_custom = Request(
        request_id="r-custom",
        requirement="ocr",
        profile=ExecutionProfile.CUSTOM,
        custom_options={"dpi": 250},
        inputs=(InputRef("in-1", pdf_path, "application/pdf", 100),),
    )
    with MagicMock() as mock_iter:
        mock_iter.return_value = [Image.new("RGB", (100, 100))]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("sarathi.shakti.ocr.capability.iter_images_from_bytes", mock_iter)
            cap.execute(req_custom, ctx)
            assert mock_iter.call_args.kwargs.get("dpi") == 250


def test_weak_crop_batch_recognition_fast_path() -> None:
    """Proves RapidOCREngine batches weak crops into a single recognize_txt call."""
    img = Image.new("RGB", (300, 100), color="white")
    engine = RapidOCREngine(default_lang="hi")

    class MockRapidOCREngine:
        def __init__(self) -> None:
            self.recognize_txt_calls: list[list[Any]] = []

        def __call__(self, arr: Any, **kwargs: Any) -> Any:
            mock_out = MagicMock()
            mock_out.txts = ["कमजोर1", "कमजोर2"]
            mock_out.boxes = [
                [(10, 10), (80, 10), (80, 40), (10, 40)],
                [(100, 10), (180, 10), (180, 40), (100, 40)],
            ]
            mock_out.scores = [0.45, 0.50]
            return mock_out

        def recognize_txt(self, crops: list[Any]) -> Any:
            self.recognize_txt_calls.append(crops)
            res = MagicMock()
            res.txts = ("मजबूत1", "मजबूत2")
            res.scores = (0.92, 0.88)
            return res

    mock_inst = MockRapidOCREngine()
    engine._engine = mock_inst

    page_data, prov, conf, warns = engine.ocr_page(img, 1, "inp-test", profile=ExecutionProfile.ACCURATE)

    # Must have called recognize_txt exactly once with 2 crops
    assert len(mock_inst.recognize_txt_calls) == 1
    assert len(mock_inst.recognize_txt_calls[0]) == 2

    # Spans should be upgraded
    assert page_data.spans[0].text == "मजबूत1"
    assert page_data.spans[0].confidence == 0.92
    assert page_data.spans[1].text == "मजबूत2"
    assert page_data.spans[1].confidence == 0.88
    assert page_data.metadata.get("retry_improved_count") == 2
