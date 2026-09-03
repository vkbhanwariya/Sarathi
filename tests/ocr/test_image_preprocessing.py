"""Tests for Pre-OCR Vision Filters and OpenCV Fallback Behavior."""

from __future__ import annotations

import unittest.mock as mock
import pytest

# Finding 26 Fix: Guard numpy import so environments without ocr optional extra skip cleanly
np = pytest.importorskip("numpy")

from sarathi.sankalpa import ExecutionProfile
from sarathi.shakti.ocr.engine import (
    RapidOCREngine,
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
    cv2 = pytest.importorskip("cv2")
    # Low-contrast image with a subtle gradient
    x = np.linspace(50, 80, 64, dtype=np.uint8)
    rgb_img = np.zeros((64, 64, 3), dtype=np.uint8)
    rgb_img[:, :] = x[:, None]

    enhanced = apply_clahe(rgb_img)
    assert enhanced.shape == (64, 64, 3)
    # Finding 25: Assert contrast enhancement actually altered the pixel values
    assert not np.array_equal(enhanced, rgb_img)

    gray_img = np.zeros((64, 64), dtype=np.uint8)
    gray_img[:, :] = x[:, None]
    enhanced_gray = apply_clahe(gray_img)
    assert enhanced_gray.shape == (64, 64)
    assert not np.array_equal(enhanced_gray, gray_img)


def test_remove_stamp_artifacts_safety() -> None:
    """Verify remove_stamp_artifacts safely passes through clean images."""
    clean_img = np.full((64, 64, 3), 255, dtype=np.uint8)
    res = remove_stamp_artifacts(clean_img)
    assert res.shape == (64, 64, 3)
    assert np.array_equal(res, clean_img)


def test_remove_stamp_artifacts_inpainting() -> None:
    """Verify remove_stamp_artifacts detects red stamp pixels and applies inpainting."""
    cv2 = pytest.importorskip("cv2")
    img = np.full((80, 80, 3), 255, dtype=np.uint8)
    # Stamp a red circle in the center (RGB red: [255, 0, 0])
    img[30:50, 30:50] = [255, 0, 0]

    inpainted = remove_stamp_artifacts(img)
    assert inpainted.shape == img.shape
    # Red patch must have been altered/inpainted
    assert not np.array_equal(inpainted[30:50, 30:50], img[30:50, 30:50])


def test_preprocess_ocr_image_defaults_are_non_destructive() -> None:
    """Findings 22 & 23 Fix: Preprocessing defaults must NOT inpaint stamps or force aggressive CLAHE."""
    img = np.full((60, 60, 3), 255, dtype=np.uint8)
    img[20:40, 20:40] = [255, 0, 0]

    # By default, remove_stamps and clahe are False
    processed = preprocess_ocr_image(img)
    # Red pixels must NOT be deleted by default
    expected_patch = np.zeros((20, 20, 3), dtype=np.uint8)
    expected_patch[:, :] = [255, 0, 0]
    assert np.array_equal(processed[20:40, 20:40], expected_patch)


def test_full_pipeline_with_cv2_present() -> None:
    """Finding 25 Fix: Verify full pipeline actually transforms image when cv2 is present."""
    cv2 = pytest.importorskip("cv2")
    # Grayscale gradient image with a red patch
    sample_img = np.zeros((100, 100, 3), dtype=np.uint8)
    sample_img[:, :] = np.linspace(40, 100, 100, dtype=np.uint8)[:, None]
    sample_img[40:60, 40:60] = [255, 0, 0]

    processed = preprocess_ocr_image(sample_img, deskew=False, clahe=True, remove_stamps=True)
    assert processed is not None
    assert processed.shape == sample_img.shape
    # Verification that real transformation occurred
    assert not np.array_equal(processed, sample_img)


def test_ocr_page_profile_preprocessing_logic() -> None:
    """Findings 22 & 23: Verify ocr_page dispatches non-destructive preprocessing per profile."""
    cv2 = pytest.importorskip("cv2")
    engine = RapidOCREngine.__new__(RapidOCREngine)
    engine._default_lang = "en"
    engine._model_labels = {}
    engine._tesseract = None
    mock_runner = mock.MagicMock(return_value=None)
    engine._get_engine = mock.MagicMock(return_value=mock_runner)

    img = np.full((60, 60, 3), 255, dtype=np.uint8)

    # 1. INSTANT profile: does not apply stamp removal or aggressive CLAHE
    with mock.patch("sarathi.shakti.ocr.engine.preprocess_ocr_image", wraps=preprocess_ocr_image) as mock_prep:
        engine.ocr_page(img, 1, "in-1", profile=ExecutionProfile.INSTANT)
        mock_prep.assert_called_once()
        _, kwargs = mock_prep.call_args
        assert kwargs["remove_stamps"] is False
        assert kwargs["clahe"] is False

    # 2. ACCURATE profile: enables clahe, but keeps remove_stamps False
    with mock.patch("sarathi.shakti.ocr.engine.preprocess_ocr_image", wraps=preprocess_ocr_image) as mock_prep:
        engine.ocr_page(img, 1, "in-1", profile=ExecutionProfile.ACCURATE)
        mock_prep.assert_called_once()
        _, kwargs = mock_prep.call_args
        assert kwargs["remove_stamps"] is False
        assert kwargs["clahe"] is True

    # 3. Explicit remove_stamps=True in custom_options: enables remove_stamps and records warning
    with mock.patch("sarathi.shakti.ocr.engine.preprocess_ocr_image", wraps=preprocess_ocr_image) as mock_prep:
        _, _, _, warns = engine.ocr_page(
            img, 1, "in-1", profile=ExecutionProfile.INSTANT, custom_options={"remove_stamps": True}
        )
        mock_prep.assert_called_once()
        _, kwargs = mock_prep.call_args
        assert kwargs["remove_stamps"] is True
        assert any(w.code == "EXPERIMENTAL_STAMP_REMOVAL" for w in warns)
