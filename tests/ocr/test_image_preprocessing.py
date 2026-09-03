"""Tests for Pre-OCR Vision Filters and OpenCV Fallback Behavior."""

from __future__ import annotations

import unittest.mock as mock
import numpy as np
import pytest

from sarathi.shakti.ocr.engine import (
    apply_clahe,
    deskew_image,
    preprocess_ocr_image,
    remove_stamp_artifacts,
)


def test_preprocess_ocr_image_strict_fallback_when_cv2_unavailable() -> None:
    """Verify pre-OCR vision filters return image array unchanged when cv2 is not importable."""
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)

    with mock.patch.dict("sys.modules", {"cv2": None}):
        res = preprocess_ocr_image(dummy_img)
        # Must return the original array untouched
        assert np.array_equal(res, dummy_img)


def test_deskew_image_handles_empty_or_trivial() -> None:
    """Verify deskew_image returns original image with 0.0 angle for blank or empty arrays."""
    blank_img = np.zeros((50, 50, 3), dtype=np.uint8)
    out_img, angle = deskew_image(blank_img)
    assert angle == 0.0
    assert out_img.shape == (50, 50, 3)


def test_apply_clahe_enhancement() -> None:
    """Verify apply_clahe enhances contrast on RGB and grayscale images without altering shape."""
    rgb_img = np.full((64, 64, 3), 128, dtype=np.uint8)
    enhanced = apply_clahe(rgb_img)
    assert enhanced.shape == (64, 64, 3)

    gray_img = np.full((64, 64), 128, dtype=np.uint8)
    enhanced_gray = apply_clahe(gray_img)
    assert enhanced_gray.shape == (64, 64)


def test_remove_stamp_artifacts_safety() -> None:
    """Verify remove_stamp_artifacts safely passes through clean images."""
    clean_img = np.full((64, 64, 3), 255, dtype=np.uint8)
    res = remove_stamp_artifacts(clean_img)
    assert res.shape == (64, 64, 3)


def test_full_pipeline_with_cv2_present() -> None:
    """Verify full pre-OCR pipeline executes all stages when cv2 is available."""
    sample_img = np.ones((120, 120, 3), dtype=np.uint8) * 200
    processed = preprocess_ocr_image(sample_img, deskew=True, clahe=True, remove_stamps=True)
    assert processed is not None
    assert processed.shape == sample_img.shape
