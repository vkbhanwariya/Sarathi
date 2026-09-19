# ruff: noqa: E402
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
    pytest.importorskip("cv2")
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
    pytest.importorskip("cv2")
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
    pytest.importorskip("cv2")
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
    pytest.importorskip("cv2")
    engine = RapidOCREngine.__new__(RapidOCREngine)
    engine._default_lang = "en"
    engine._model_labels = {}
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


def test_bug_O10_deskew_angle_estimation() -> None:
    """O10: Verify deskew estimates text line angle, not bounding box of asymmetric ink or borders."""
    cv2 = pytest.importorskip("cv2")

    # 1. Text lines rotated by +3 degrees
    img_p3 = np.full((800, 600, 3), 255, dtype=np.uint8)
    for y in range(100, 700, 50):
        cv2.putText(
            img_p3,
            "The quick brown fox jumps over the lazy dog 12345",
            (50, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            2,
        )
    m_p3 = cv2.getRotationMatrix2D((300, 400), 3.0, 1.0)
    img_p3 = cv2.warpAffine(img_p3, m_p3, (600, 800), borderValue=(255, 255, 255))
    _, angle_p3 = deskew_image(img_p3)
    assert abs(abs(angle_p3) - 3.0) <= 0.5

    # 2. Text lines rotated by -3 degrees
    img_m3 = np.full((800, 600, 3), 255, dtype=np.uint8)
    for y in range(100, 700, 50):
        cv2.putText(
            img_m3,
            "The quick brown fox jumps over the lazy dog 12345",
            (50, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 0),
            2,
        )
    m_m3 = cv2.getRotationMatrix2D((300, 400), -3.0, 1.0)
    img_m3 = cv2.warpAffine(img_m3, m_m3, (600, 800), borderValue=(255, 255, 255))
    _, angle_m3 = deskew_image(img_m3)
    assert abs(abs(angle_m3) - 3.0) <= 0.5

    # 3. 0 deg skew page with full-page border and horizontal table rows
    img_border = np.full((800, 600, 3), 255, dtype=np.uint8)
    cv2.rectangle(img_border, (20, 20), (580, 780), (0, 0, 0), 2)
    for y in range(100, 700, 60):
        cv2.putText(
            img_border,
            "Regular horizontal text row inside table",
            (50, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 0),
            1,
        )
    out_b, angle_b = deskew_image(img_border)
    assert angle_b == 0.0
    assert np.array_equal(out_b, img_border)

    # 4. 0 deg skew page with asymmetric layout (title top-left, signature bottom-right)
    # On unpatched code, minAreaRect over ink bounding box computes ~ -24.8 deg and rotates!
    img_asym = np.full((800, 600, 3), 255, dtype=np.uint8)
    cv2.putText(img_asym, "OFFICIAL NOTICE", (50, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    cv2.putText(img_asym, "Authorized Signatory", (350, 750), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    out_asym, angle_asym = deskew_image(img_asym)
    assert angle_asym == 0.0
    assert np.array_equal(out_asym, img_asym)
