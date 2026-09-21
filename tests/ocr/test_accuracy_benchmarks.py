"""Automated tests for Phase 3: Adaptive DPI Resolution, Table Fidelity, and Accuracy Benchmarks."""

from __future__ import annotations

from typing import Any
from unittest import mock

import numpy as np
from PIL import Image

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import (
    RapidOCREngine,
    resolve_ocr_dpi,
)
from sarathi.shakti.ocr.engine.factory import build_rapidocr_instance


def test_resolve_ocr_dpi_profile_triage() -> None:
    """Verify resolve_ocr_dpi returns 150 for INSTANT, 200 for ACCURATE, and 250 for high_dpi."""
    # Profile-driven resolution
    assert resolve_ocr_dpi(ExecutionProfile.INSTANT) == 150
    assert resolve_ocr_dpi("instant") == 150
    assert resolve_ocr_dpi(ExecutionProfile.ACCURATE) == 200
    assert resolve_ocr_dpi(ExecutionProfile.LAYOUT_PRESERVING) == 200
    assert resolve_ocr_dpi(None) == 200

    # Custom options override
    assert resolve_ocr_dpi(ExecutionProfile.INSTANT, {"dpi": 300}) == 300
    assert resolve_ocr_dpi(ExecutionProfile.ACCURATE, {"dpi": 144}) == 144
    assert resolve_ocr_dpi(ExecutionProfile.ACCURATE, {"high_dpi": True}) == 250

    # Graceful fallback on invalid values
    assert resolve_ocr_dpi(ExecutionProfile.ACCURATE, {"dpi": "invalid"}) == 200
    assert resolve_ocr_dpi(ExecutionProfile.INSTANT, {"dpi": 10}) == 150
    assert resolve_ocr_dpi(ExecutionProfile.ACCURATE, {"dpi": 1200}) == 200


def test_reconstruct_layout_morphological_ruled_table_detection() -> None:
    """Verify reconstruct_layout extracts ruled tables when given an image array with grid lines."""
    from sarathi.sankalpa import TextSpan
    from sarathi.shakti.ocr.engine.layout import reconstruct_layout

    # Draw synthetic image with black grid lines for ruled table detection
    img = Image.new("RGB", (250, 100), color="white")
    import cv2

    img_arr = np.array(img)
    # Horizontal grid lines
    cv2.line(img_arr, (5, 5), (200, 5), (0, 0, 0), 2)
    cv2.line(img_arr, (5, 35), (200, 35), (0, 0, 0), 2)
    cv2.line(img_arr, (5, 65), (200, 65), (0, 0, 0), 2)
    # Vertical grid lines
    cv2.line(img_arr, (5, 5), (5, 65), (0, 0, 0), 2)
    cv2.line(img_arr, (100, 5), (100, 65), (0, 0, 0), 2)
    cv2.line(img_arr, (200, 5), (200, 65), (0, 0, 0), 2)

    spans = [
        TextSpan(text="Invoice No", confidence=0.95, bounding_box=(10.0, 10.0, 90.0, 30.0)),
        TextSpan(text="Amount", confidence=0.95, bounding_box=(110.0, 10.0, 190.0, 30.0)),
        TextSpan(text="INV-001", confidence=0.95, bounding_box=(10.0, 40.0, 90.0, 60.0)),
        TextSpan(text="1,000.00", confidence=0.95, bounding_box=(110.0, 40.0, 190.0, 60.0)),
    ]

    # With img_arr and preserve_layout=True, morphological line detection yields tables
    text, tables = reconstruct_layout(img_arr, spans, preserve_layout=True)
    assert len(tables) >= 1
    tbl = tables[0]
    assert len(tbl.rows) >= 1
    assert len(tbl.headers) >= 1

    # Invariant: Scanned OCR page coordinator bypasses table extraction to preserve reading order
    engine = RapidOCREngine(default_lang="en")
    page_data, _, _, _ = engine.ocr_page(
        image=Image.fromarray(img_arr),
        page_number=1,
        input_id="inp-scanned",
        profile=ExecutionProfile.ACCURATE,
    )
    assert len(page_data.tables) == 0


def test_build_rapidocr_instance_rec_batch_override(tmp_path: Any) -> None:
    """Verify build_rapidocr_instance respects rec_batch_num override and device defaults."""
    with (
        mock.patch("sarathi.shakti.ocr.engine.factory.verify_ocr_manifest_and_models") as mock_verify,
        mock.patch("sarathi.shakti.ocr.engine.factory.patch_rapidocr_openvino_device"),
        mock.patch("rapidocr.RapidOCR") as mock_rapidocr,
    ):
        mock_verify.return_value = {"det": "d.onnx", "cls": "c.onnx", "rec_devanagari": "r.onnx"}

        # Custom batch number
        build_rapidocr_instance(
            data_root=tmp_path,
            lang="hi",
            target_device="GPU",
            verified_model_paths={},
            rec_batch_num=64,
        )
        _, kwargs = mock_rapidocr.call_args
        params = kwargs.get("params", {})
        assert params.get("Rec.rec_batch_num") == 64

        # Default GPU batch size (48)
        build_rapidocr_instance(
            data_root=tmp_path,
            lang="hi",
            target_device="GPU",
            verified_model_paths={},
        )
        _, kwargs = mock_rapidocr.call_args
        params = kwargs.get("params", {})
        assert params.get("Rec.rec_batch_num") == 48

        # Default CPU batch size (16)
        build_rapidocr_instance(
            data_root=tmp_path,
            lang="hi",
            target_device="CPU",
            verified_model_paths={},
        )
        _, kwargs = mock_rapidocr.call_args
        params = kwargs.get("params", {})
        assert params.get("Rec.rec_batch_num") == 16
